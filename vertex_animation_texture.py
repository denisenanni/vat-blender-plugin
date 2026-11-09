# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Denise Nanni

bl_info = {
    "name": "Vertex Animation Texture Exporter",
    "author": "Denise Nanni",
    "version": (1, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > VAT",
    "description": "Bake mesh animation to vertex animation textures for game engines",
    "category": "Animation",
}

import json
import math
import os

import bpy
import numpy as np

LOOKUP_UV_NAME = "VAT_Lookup"

# Engine presets: 3x3 axis conversion applied to offsets/normals, and a unit scale
# applied to offsets. They must match what the engine's FBX importer does to the
# mesh, otherwise the offsets point the wrong way.
#   Unreal: Z-up, left-handed, centimetres -> Blender (x, y, z) becomes (x, -y, z) * 100
#   Blender: raw Blender object-space coordinates (for previewing / custom pipelines)
ENGINE_PRESETS = {
    'UNREAL': (np.array([[1, 0, 0], [0, -1, 0], [0, 0, 1]], dtype=np.float64), 100.0),
    'BLENDER': (np.eye(3, dtype=np.float64), 1.0),
}


def next_pow2(n):
    return 1 if n <= 1 else 2 ** (int(n) - 1).bit_length()


def compute_layout(vertex_count, frame_count, max_width, pow2_height):
    """Where every vertex/frame lives in the texture.

    Vertices wrap across rows: each frame is a block of `rows_per_frame` rows,
    frame 0 is the TOP block of the image file, frame f starts at file row
    f * rows_per_frame. Padding (pow2 height) is at the bottom of the file.
    """
    width = min(next_pow2(vertex_count), next_pow2(max_width))
    rows_per_frame = math.ceil(vertex_count / width)
    used_height = rows_per_frame * frame_count
    height = next_pow2(used_height) if pow2_height else used_height
    return width, height, rows_per_frame


def lookup_uvs(vertex_count, width, height):
    """Per-vertex lookup UV in Blender's UV convention (V=0 at the bottom of the image).

    It points at the vertex's texel in frame 0. After FBX import into a top-left
    UV engine (Unreal) this becomes ((col+0.5)/W, (row+0.5)/H) measured from the top.
    """
    idx = np.arange(vertex_count)
    col = idx % width
    row = idx // width  # file row from the top, within frame 0
    u = (col + 0.5) / width
    v = 1.0 - (row + 0.5) / height
    return np.stack([u, v], axis=1).astype(np.float32)


def evaluated_mesh_data(obj, depsgraph):
    """Local-space vertex positions and normals of the evaluated object."""
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        n = len(mesh.vertices)
        co = np.empty(n * 3, dtype=np.float32)
        nrm = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', co)
        mesh.vertices.foreach_get('normal', nrm)
        return co.reshape(n, 3).astype(np.float64), nrm.reshape(n, 3).astype(np.float64)
    finally:
        obj_eval.to_mesh_clear()


def bake(context, obj, start, end, engine):
    """Return (offsets, normals, rest) in engine space. offsets[f, v] is relative to rest."""
    scene = context.scene
    axis, scale = ENGINE_PRESETS[engine]
    original_frame = scene.frame_current
    frames = list(range(start, end + 1))
    wm = context.window_manager
    wm.progress_begin(0, len(frames))
    offsets, normals = [], []
    try:
        rest = rest_inv = None
        for i, frame in enumerate(frames):
            scene.frame_set(frame)
            depsgraph = context.evaluated_depsgraph_get()
            co, nrm = evaluated_mesh_data(obj, depsgraph)
            world = np.array(obj.evaluated_get(depsgraph).matrix_world, dtype=np.float64)
            if rest is None:
                rest_inv = np.linalg.inv(world)
                rest = co
            elif len(co) != len(rest):
                raise ValueError(
                    f"Vertex count changed: frame {start} has {len(rest)} vertices, frame {frame} has "
                    f"{len(co)}. VAT needs constant topology (check Remesh/Decimate/fluid modifiers).")
            # Bring this frame into the rest frame's object space, so object-level
            # animation (location/rotation/scale keys, parenting) is baked too.
            rel = rest_inv @ world
            local = co @ rel[:3, :3].T + rel[:3, 3]
            n_mat = np.linalg.inv(rel[:3, :3]).T
            n = nrm @ n_mat.T
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            offsets.append(((local - rest) @ axis.T) * scale)
            normals.append(n @ axis.T)
            wm.progress_update(i)
    finally:
        wm.progress_end()
        scene.frame_set(original_frame)
    return np.array(offsets), np.array(normals), rest


def pack_texture(per_frame, width, height, rows_per_frame):
    """(frames, verts, 3) -> RGBA float array in FILE order (row 0 = top of image)."""
    frames, verts, _ = per_frame.shape
    out = np.zeros((height, width, 4), dtype=np.float32)
    out[..., 3] = 1.0
    padded = np.zeros((frames, rows_per_frame * width, 3), dtype=np.float32)
    padded[:, :verts] = per_frame
    block = padded.reshape(frames * rows_per_frame, width, 3)
    out[:frames * rows_per_frame, :, :3] = block
    return out


def save_exr(name, file_rows, path):
    """Write a float32 EXR. file_rows is in file order (top row first)."""
    height, width, _ = file_rows.shape
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    image = bpy.data.images.new(name, width=width, height=height, alpha=True, float_buffer=True)
    try:
        image.colorspace_settings.name = 'Non-Color'
        # Blender's pixel buffer starts at the bottom row.
        image.pixels.foreach_set(np.ascontiguousarray(np.flipud(file_rows)).ravel())
        image.filepath_raw = path
        image.file_format = 'OPEN_EXR'
        image.save()
    finally:
        bpy.data.images.remove(image)


def export_mesh_fbx(context, obj, path, uvs):
    """Export the rest-frame mesh (object space, no transform) with the lookup UV as the last UV map."""
    depsgraph = context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    if LOOKUP_UV_NAME in mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[LOOKUP_UV_NAME])
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    layer = mesh.uv_layers.new(name=LOOKUP_UV_NAME)
    if layer is None:
        bpy.data.meshes.remove(mesh)
        raise RuntimeError("Mesh already has the maximum number of UV maps (8); remove one.")
    loop_vert = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get('vertex_index', loop_vert)
    layer.data.foreach_set('uv', uvs[loop_vert].ravel())

    tmp = bpy.data.objects.new(f"{obj.name}_VAT", mesh)
    context.scene.collection.objects.link(tmp)
    view_layer = context.view_layer
    prev_selected = [o for o in view_layer.objects if o.select_get()]
    prev_active = view_layer.objects.active
    try:
        for o in prev_selected:
            o.select_set(False)
        tmp.select_set(True)
        view_layer.objects.active = tmp
        bpy.ops.export_scene.fbx(
            filepath=path, use_selection=True, object_types={'MESH'},
            use_mesh_modifiers=False, mesh_smooth_type='FACE', bake_anim=False,
            add_leaf_bones=False)
    finally:
        bpy.data.objects.remove(tmp)
        bpy.data.meshes.remove(mesh)
        for o in prev_selected:
            if o.name in view_layer.objects:
                o.select_set(True)
        view_layer.objects.active = prev_active


def run_export(context, obj, props):
    """Do the whole export. Returns the metadata dict. Raises on failure."""
    start, end = props.start_frame, props.end_frame
    if start > end:
        raise ValueError("Start frame must be <= end frame")
    export_dir = bpy.path.abspath(props.export_path)
    if props.export_path.startswith("//") and not bpy.data.filepath:
        raise ValueError("Save the .blend file first, or set an absolute export path")
    os.makedirs(export_dir, exist_ok=True)

    offsets, normals, rest = bake(context, obj, start, end, props.target_engine)
    frame_count, vertex_count = offsets.shape[:2]
    if vertex_count == 0:
        raise ValueError("Mesh has no vertices")
    width, height, rows = compute_layout(vertex_count, frame_count, props.max_texture_width,
                                         props.power_of_two_height)
    base = os.path.join(export_dir, props.texture_name)
    files = {}

    files["position"] = base + "_offset.exr"
    save_exr(f"{props.texture_name}_offset", pack_texture(offsets, width, height, rows), files["position"])
    if props.export_normals:
        files["normal"] = base + "_normal.exr"
        save_exr(f"{props.texture_name}_normal", pack_texture(normals, width, height, rows), files["normal"])

    uvs = lookup_uvs(vertex_count, width, height)
    if props.export_mesh:
        files["mesh"] = base + "_mesh.fbx"
        original_frame = context.scene.frame_current
        context.scene.frame_set(start)
        try:
            export_mesh_fbx(context, obj, files["mesh"], uvs)
        finally:
            context.scene.frame_set(original_frame)

    flat = offsets.reshape(-1, 3)
    metadata = {
        "format_version": 2,
        "object_name": obj.name,
        "target_engine": props.target_engine,
        "data": "offset_from_rest_object_space",
        "vertex_count": int(vertex_count),
        "frame_count": int(frame_count),
        "start_frame": start,
        "end_frame": end,
        "fps": context.scene.render.fps / context.scene.render.fps_base,
        "texture_width": width,
        "texture_height": height,
        "rows_per_frame": rows,
        # Add frame * frame_v_stride to the lookup UV's V in top-left-UV engines (Unreal).
        "frame_v_stride": rows / height,
        "lookup_uv_map": LOOKUP_UV_NAME,
        "offset_min": flat.min(axis=0).tolist(),
        "offset_max": flat.max(axis=0).tolist(),
        "files": {k: os.path.basename(v) for k, v in files.items()},
    }
    with open(base + "_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    return metadata


class VAT_Properties(bpy.types.PropertyGroup):
    export_path: bpy.props.StringProperty(name="Export Path", default="//", subtype='DIR_PATH')
    texture_name: bpy.props.StringProperty(name="Name", default="VAT")
    start_frame: bpy.props.IntProperty(name="Start", default=1)
    end_frame: bpy.props.IntProperty(name="End", default=250)
    target_engine: bpy.props.EnumProperty(
        name="Target",
        items=[('UNREAL', "Unreal Engine", "Z-up, left-handed, centimetres"),
               ('BLENDER', "Raw Blender", "Blender object space, metres (custom pipelines)")],
        default='UNREAL')
    max_texture_width: bpy.props.IntProperty(
        name="Max Width", description="Vertices wrap onto extra rows past this width (rounded to power of 2)",
        default=4096, min=16, max=16384)
    export_normals: bpy.props.BoolProperty(name="Export Normals", default=True)
    export_mesh: bpy.props.BoolProperty(
        name="Export Mesh (FBX)", description="Export the rest mesh with the VAT_Lookup UV map. "
        "Required: engines re-order vertices on import, so the lookup UV is how the shader finds its texel",
        default=True)
    power_of_two_height: bpy.props.BoolProperty(name="Power of 2 Height", default=False)


class VAT_OT_Export(bpy.types.Operator):
    """Bake the active mesh's animation to vertex animation textures"""
    bl_idname = "vat.export"
    bl_label = "Export VAT"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def execute(self, context):
        try:
            meta = run_export(context, context.active_object, context.scene.vat_props)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"VAT export failed: {e}")
            return {'CANCELLED'}
        if meta["texture_height"] > 8192:
            self.report({'WARNING'}, f"Texture is {meta['texture_width']}x{meta['texture_height']}; "
                        "many engines/GPUs cap at 8192. Bake fewer frames or raise Max Width.")
        self.report({'INFO'}, f"VAT exported: {meta['texture_width']}x{meta['texture_height']}, "
                    f"{meta['vertex_count']} verts, {meta['frame_count']} frames")
        return {'FINISHED'}


class VAT_OT_Use_Scene_Range(bpy.types.Operator):
    """Copy the scene's frame range"""
    bl_idname = "vat.use_scene_range"
    bl_label = "Use Scene Range"

    def execute(self, context):
        props = context.scene.vat_props
        props.start_frame, props.end_frame = context.scene.frame_start, context.scene.frame_end
        return {'FINISHED'}


class VAT_PT_Panel(bpy.types.Panel):
    bl_label = "Vertex Animation Texture"
    bl_idname = "VAT_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VAT'

    def draw(self, context):
        layout = self.layout
        props = context.scene.vat_props
        obj = context.active_object
        if obj and obj.type == 'MESH':
            box = layout.box()
            box.label(text=f"{obj.name}: {len(obj.data.vertices)} base verts")
            frames = max(0, props.end_frame - props.start_frame + 1)
            # Base vertex count is a cheap estimate; modifiers may change it.
            w, h, _ = compute_layout(max(1, len(obj.data.vertices)), max(1, frames),
                                     props.max_texture_width, props.power_of_two_height)
            box.label(text=f"≈ {w} x {h} texture")
        else:
            layout.label(text="Select a mesh object", icon='ERROR')

        layout.prop(props, "target_engine")
        layout.prop(props, "export_path")
        layout.prop(props, "texture_name")
        row = layout.row(align=True)
        row.prop(props, "start_frame")
        row.prop(props, "end_frame")
        layout.operator("vat.use_scene_range", icon='TIME')
        layout.prop(props, "max_texture_width")
        layout.prop(props, "export_normals")
        layout.prop(props, "export_mesh")
        layout.prop(props, "power_of_two_height")
        row = layout.row()
        row.scale_y = 1.5
        row.operator("vat.export", icon='EXPORT')


classes = (VAT_Properties, VAT_OT_Export, VAT_OT_Use_Scene_Range, VAT_PT_Panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vat_props = bpy.props.PointerProperty(type=VAT_Properties)


def unregister():
    del bpy.types.Scene.vat_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
