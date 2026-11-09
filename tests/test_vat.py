"""Headless tests for the VAT exporter.

Run outside Blender with the `bpy` wheel:

    python -m venv .venv && .venv/bin/pip install bpy pytest OpenEXR
    .venv/bin/python -m pytest tests

The EXRs are read back with the OpenEXR library (not Blender), and the FBX is
re-imported and looked up purely through its VAT_Lookup UV map, the way an
engine shader would, so the tests check the files rather than our own code.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
import OpenEXR
import pytest
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import vertex_animation_texture as vat  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def addon():
    vat.register()
    yield
    vat.unregister()


@pytest.fixture
def scene(tmp_path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "vat_props"):
        vat.register()
    props = bpy.context.scene.vat_props
    props.export_path = str(tmp_path) + os.sep
    props.texture_name = "T"
    return props


def read_exr(path):
    """RGB float array in file order (row 0 = top of the image)."""
    with OpenEXR.File(path) as f:
        ch = f.channels()
        if "RGBA" in ch or "RGB" in ch:
            px = ch.get("RGBA", ch.get("RGB")).pixels
            return px[..., :3].astype(np.float64), px.dtype
        r, g, b = (ch[c].pixels for c in "RGB")
        return np.stack([r, g, b], axis=-1).astype(np.float64), r.dtype


def to_unreal(v):
    return np.array([v[0], -v[1], v[2]]) * 100.0


def expected_offsets(obj, start, end):
    """Independent reference: per-vertex rest-relative offsets in Unreal space via mathutils."""
    scene = bpy.context.scene
    out = []
    rest = rest_inv = None
    for f in range(start, end + 1):
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        world = [ev.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
        if rest is None:
            rest_inv = ev.matrix_world.inverted()
            rest = [rest_inv @ p for p in world]
        out.append([to_unreal(rest_inv @ p - r) for p, r in zip(world, rest)])
    return np.array(out), np.array([tuple(r) for r in rest])


def sample_like_unreal(meta, tex, fbx_path, rest):
    """Import the FBX, then for every loop sample the texture with its lookup UV.

    Returns (frames, n_loops, 3) samples and the rest-vertex index of each loop
    (found by position, NOT by index, since engines re-order vertices).
    """
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=fbx_path)
    obj = next(o for o in bpy.data.objects if o not in before and o.type == 'MESH')
    me = obj.data
    assert vat.LOOKUP_UV_NAME in me.uv_layers, "lookup UV map missing from FBX"
    uv_layer = me.uv_layers[vat.LOOKUP_UV_NAME]
    world = obj.matrix_world
    kd = KDTree(len(rest))
    for i, p in enumerate(rest):
        kd.insert(Vector(p), i)
    kd.balance()
    W, H = meta["texture_width"], meta["texture_height"]
    stride = meta["frame_v_stride"]
    idx, samples = [], []
    for loop in me.loops:
        pos = world @ me.vertices[loop.vertex_index].co
        _, i, dist = kd.find(pos)
        assert dist < 1e-4
        idx.append(i)
        u, v = uv_layer.data[loop.index].uv
        v_unreal = 1.0 - v  # Unreal's FBX import flips V; V=0 is the top of the texture
        per_frame = []
        for f in range(meta["frame_count"]):
            vf = v_unreal + f * stride
            per_frame.append(tex[int(math.floor(vf * H)), int(math.floor(u * W))])
        samples.append(per_frame)
    return np.array(samples).transpose(1, 0, 2), np.array(idx)


def animated_sphere(segments=32, rings=16, location=(3, 1, 0)):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=location)
    obj = bpy.context.active_object
    # Object-level animation: move and rotate.
    obj.keyframe_insert("location", frame=1)
    obj.keyframe_insert("rotation_euler", frame=1)
    obj.location.z += 2
    obj.rotation_euler.z = 1.0
    obj.keyframe_insert("location", frame=10)
    obj.keyframe_insert("rotation_euler", frame=10)
    # Deformation: a simple deform modifier animated over time.
    mod = obj.modifiers.new("twist", 'SIMPLE_DEFORM')
    mod.angle = 0.0
    mod.keyframe_insert("angle", frame=1)
    mod.angle = 1.2
    mod.keyframe_insert("angle", frame=10)
    return obj


def export(props, start=1, end=10, **kw):
    props.start_frame, props.end_frame = start, end
    for k, v in kw.items():
        setattr(props, k, v)
    assert bpy.ops.vat.export() == {'FINISHED'}
    base = os.path.join(bpy.path.abspath(props.export_path), props.texture_name)
    with open(base + "_metadata.json") as f:
        return json.load(f), base


def check_roundtrip(obj, props, **kw):
    expected, rest = expected_offsets(obj, kw.get("start", 1), kw.get("end", 10))
    meta, base = export(props, **kw)
    tex, dtype = read_exr(base + "_offset.exr")
    assert dtype == np.float32, "offset texture must be full float"
    assert tex.shape == (meta["texture_height"], meta["texture_width"], 3)
    samples, idx = sample_like_unreal(meta, tex, base + "_mesh.fbx", rest)
    np.testing.assert_allclose(samples, expected[:, idx], atol=1e-3)
    return meta, base, tex


def test_roundtrip_deforming_moving_object(scene):
    obj = animated_sphere()
    meta, _, _ = check_roundtrip(obj, scene)
    assert meta["rows_per_frame"] == 1


def test_many_vertices_wrap_rows(scene):
    # 3122 verts with a 1024 max width -> 4 rows per frame. Used to crash.
    obj = animated_sphere(segments=80, rings=40)
    meta, _, _ = check_roundtrip(obj, scene, max_texture_width=1024)
    assert meta["texture_width"] == 1024
    assert meta["rows_per_frame"] == math.ceil(meta["vertex_count"] / 1024)
    assert meta["texture_height"] == meta["rows_per_frame"] * meta["frame_count"]


def test_default_width_handles_large_mesh(scene):
    obj = animated_sphere(segments=80, rings=40)  # > 2048 verts, old default crashed here
    meta, _ = export(scene)
    assert meta["vertex_count"] > 2048


def test_pow2_height_pads_at_bottom(scene):
    obj = animated_sphere()
    meta, _, tex = check_roundtrip(obj, scene, power_of_two_height=True, end=12)
    used = meta["rows_per_frame"] * meta["frame_count"]
    assert meta["texture_height"] == 16 and used == 12
    assert np.all(tex[used:] == 0)


def test_first_frame_is_zero_offset(scene):
    animated_sphere()
    meta, base = export(scene)
    tex, _ = read_exr(base + "_offset.exr")
    assert np.allclose(tex[0, :meta["vertex_count"]], 0, atol=1e-6)


def test_normals_unit_length(scene):
    animated_sphere()
    meta, base = export(scene)
    n, _ = read_exr(base + "_normal.exr")
    used = n[:meta["frame_count"] * meta["rows_per_frame"]].reshape(-1, 3)[:meta["vertex_count"]]
    np.testing.assert_allclose(np.linalg.norm(used, axis=1), 1, atol=1e-4)


def test_pure_translation_maps_to_unreal_axes(scene):
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    obj.keyframe_insert("location", frame=1)
    obj.location = (1, 2, 3)
    obj.keyframe_insert("location", frame=2)
    meta, base = export(scene, start=1, end=2)
    tex, _ = read_exr(base + "_offset.exr")
    np.testing.assert_allclose(tex[1, :8], np.tile([100, -200, 300], (8, 1)), atol=1e-3)


def test_topology_change_fails_cleanly(scene):
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    mod = obj.modifiers.new("sub", 'SUBSURF')
    mod.levels = 0
    mod.keyframe_insert("levels", frame=1)
    mod.levels = 2
    mod.keyframe_insert("levels", frame=5)
    scene.start_frame, scene.end_frame = 1, 5
    with pytest.raises(RuntimeError, match="Vertex count changed"):
        bpy.ops.vat.export()


def test_restores_frame_and_selection(scene):
    obj = animated_sphere()
    bpy.context.scene.frame_set(7)
    export(scene)
    assert bpy.context.scene.frame_current == 7
    assert bpy.context.view_layer.objects.active == obj
    assert [o.name for o in bpy.data.objects] == [obj.name]
