bl_info = {
    "name": "Vertex Animation Texture Exporter",
    "author": "Bro",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > VAT",
    "description": "Export vertex animation as textures for use in game engines",
    "category": "Animation",
}

import bpy
import bmesh
import numpy as np
from mathutils import Vector
import os

class VAT_Properties(bpy.types.PropertyGroup):
    export_path: bpy.props.StringProperty(
        name="Export Path",
        description="Directory to export VAT textures",
        default="//",
        subtype='DIR_PATH'
    )
    
    texture_name: bpy.props.StringProperty(
        name="Texture Name",
        description="Base name for exported textures",
        default="VAT"
    )
    
    start_frame: bpy.props.IntProperty(
        name="Start Frame",
        description="First frame to bake",
        default=1,
        min=0
    )
    
    end_frame: bpy.props.IntProperty(
        name="End Frame",
        description="Last frame to bake",
        default=250,
        min=1
    )
    
    export_normals: bpy.props.BoolProperty(
        name="Export Normals",
        description="Export normal data as separate texture",
        default=True
    )
    
    normalize_bounds: bpy.props.BoolProperty(
        name="Normalize to Bounds",
        description="Normalize position data to object bounds (0-1 range)",
        default=True
    )
    
    texture_width: bpy.props.IntProperty(
        name="Texture Width",
        description="Width of output texture (should match vertex count)",
        default=2048,
        min=1,
        max=16384
    )


class VAT_OT_Calculate_Texture_Size(bpy.types.Operator):
    """Calculate optimal texture size based on mesh vertex count"""
    bl_idname = "vat.calculate_texture_size"
    bl_label = "Calculate Texture Size"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object")
            return {'CANCELLED'}
        
        # Get vertex count
        vertex_count = len(obj.data.vertices)
        frame_count = context.scene.vat_props.end_frame - context.scene.vat_props.start_frame + 1
        
        # Calculate texture dimensions
        # Width = vertex count, Height = frame count
        # Round up to nearest power of 2 for width
        width = 2 ** (vertex_count - 1).bit_length()
        height = frame_count
        
        context.scene.vat_props.texture_width = width
        
        self.report({'INFO'}, f"Texture size: {width}x{height} (Vertices: {vertex_count}, Frames: {frame_count})")
        return {'FINISHED'}


class VAT_OT_Export(bpy.types.Operator):
    """Export Vertex Animation Texture"""
    bl_idname = "vat.export"
    bl_label = "Export VAT"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.vat_props
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object")
            return {'CANCELLED'}
        
        # Get export path
        export_path = bpy.path.abspath(props.export_path)
        if not os.path.exists(export_path):
            os.makedirs(export_path)
        
        # Store original frame
        original_frame = context.scene.frame_current
        
        try:
            # Export position texture
            self.export_position_texture(context, obj, export_path)
            
            # Export normal texture if enabled
            if props.export_normals:
                self.export_normal_texture(context, obj, export_path)
            
            # Export metadata
            self.export_metadata(context, obj, export_path)
            
            self.report({'INFO'}, f"VAT exported successfully to {export_path}")
            
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}
        
        finally:
            # Restore original frame
            context.scene.frame_set(original_frame)
        
        return {'FINISHED'}
    
    def get_mesh_data(self, context, obj, frame):
        """Get mesh vertex positions at a specific frame"""
        context.scene.frame_set(frame)
        
        # Apply modifiers to get final mesh
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        
        # Get world space positions
        world_matrix = obj.matrix_world
        positions = np.array([world_matrix @ v.co for v in mesh.vertices])
        normals = np.array([world_matrix.to_3x3() @ v.normal for v in mesh.vertices])
        
        obj_eval.to_mesh_clear()
        
        return positions, normals
    
    def normalize_positions(self, positions, bounds_min, bounds_max):
        """Normalize positions to 0-1 range based on bounds"""
        bounds_range = bounds_max - bounds_min
        # Avoid division by zero
        bounds_range = np.where(bounds_range == 0, 1, bounds_range)
        normalized = (positions - bounds_min) / bounds_range
        return normalized
    
    def export_position_texture(self, context, obj, export_path):
        """Export vertex positions as texture"""
        props = context.scene.vat_props
        
        vertex_count = len(obj.data.vertices)
        frame_count = props.end_frame - props.start_frame + 1
        
        # Initialize position array
        width = props.texture_width
        height = frame_count
        
        # Create array to store all positions (height=frames, width=vertices, channels=RGB)
        position_data = np.zeros((height, width, 3), dtype=np.float32)
        
        # Collect all positions first to calculate bounds
        all_positions = []
        for frame_idx, frame in enumerate(range(props.start_frame, props.end_frame + 1)):
            positions, _ = self.get_mesh_data(context, obj, frame)
            all_positions.append(positions)
        
        all_positions = np.array(all_positions)
        
        # Calculate bounds across all frames
        bounds_min = np.min(all_positions, axis=(0, 1))
        bounds_max = np.max(all_positions, axis=(0, 1))
        
        # Fill position data
        for frame_idx, positions in enumerate(all_positions):
            if props.normalize_bounds:
                positions = self.normalize_positions(positions, bounds_min, bounds_max)
            
            # Store positions in texture (pad with zeros if needed)
            position_data[frame_idx, :len(positions)] = positions
        
        # Convert to 0-255 range for image export
        if not props.normalize_bounds:
            # If not normalized, we need to map to 0-1 range for texture
            position_data = self.normalize_positions(position_data, bounds_min, bounds_max)
        
        # Create Blender image
        image_name = f"{props.texture_name}_position"
        
        # Remove existing image if it exists
        if image_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[image_name])
        
        image = bpy.data.images.new(image_name, width=width, height=height, alpha=False, float_buffer=True)
        
        # Flatten and set pixels (Blender expects RGBA, so we add alpha channel)
        pixels = np.zeros((height, width, 4), dtype=np.float32)
        pixels[:, :, :3] = position_data
        pixels[:, :, 3] = 1.0  # Alpha
        
        image.pixels = pixels.flatten()
        
        # Save as EXR for 32-bit precision
        image.filepath_raw = os.path.join(export_path, f"{props.texture_name}_position.exr")
        image.file_format = 'OPEN_EXR'
        image.save()
        
        print(f"Position texture exported: {image.filepath_raw}")
        print(f"Bounds: Min={bounds_min}, Max={bounds_max}")
    
    def export_normal_texture(self, context, obj, export_path):
        """Export vertex normals as texture"""
        props = context.scene.vat_props
        
        vertex_count = len(obj.data.vertices)
        frame_count = props.end_frame - props.start_frame + 1
        
        width = props.texture_width
        height = frame_count
        
        # Create array for normals
        normal_data = np.zeros((height, width, 3), dtype=np.float32)
        
        # Fill normal data
        for frame_idx, frame in enumerate(range(props.start_frame, props.end_frame + 1)):
            _, normals = self.get_mesh_data(context, obj, frame)
            
            # Normalize normals to 0-1 range (from -1 to 1)
            normals = (normals + 1.0) / 2.0
            
            normal_data[frame_idx, :len(normals)] = normals
        
        # Create Blender image
        image_name = f"{props.texture_name}_normal"
        
        if image_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[image_name])
        
        image = bpy.data.images.new(image_name, width=width, height=height, alpha=False, float_buffer=True)
        
        # Set pixels
        pixels = np.zeros((height, width, 4), dtype=np.float32)
        pixels[:, :, :3] = normal_data
        pixels[:, :, 3] = 1.0
        
        image.pixels = pixels.flatten()
        
        # Save as EXR
        image.filepath_raw = os.path.join(export_path, f"{props.texture_name}_normal.exr")
        image.file_format = 'OPEN_EXR'
        image.save()
        
        print(f"Normal texture exported: {image.filepath_raw}")
    
    def export_metadata(self, context, obj, export_path):
        """Export metadata JSON file"""
        props = context.scene.vat_props
        
        # Collect bounds
        all_positions = []
        for frame in range(props.start_frame, props.end_frame + 1):
            positions, _ = self.get_mesh_data(context, obj, frame)
            all_positions.append(positions)
        
        all_positions = np.array(all_positions)
        bounds_min = np.min(all_positions, axis=(0, 1))
        bounds_max = np.max(all_positions, axis=(0, 1))
        
        metadata = {
            "vertex_count": len(obj.data.vertices),
            "frame_count": props.end_frame - props.start_frame + 1,
            "start_frame": props.start_frame,
            "end_frame": props.end_frame,
            "fps": context.scene.render.fps,
            "texture_width": props.texture_width,
            "texture_height": props.end_frame - props.start_frame + 1,
            "bounds_min": bounds_min.tolist(),
            "bounds_max": bounds_max.tolist(),
            "normalize_bounds": props.normalize_bounds,
            "has_normals": props.export_normals
        }
        
        import json
        metadata_path = os.path.join(export_path, f"{props.texture_name}_metadata.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"Metadata exported: {metadata_path}")


class VAT_PT_Panel(bpy.types.Panel):
    """Vertex Animation Texture Panel"""
    bl_label = "Vertex Animation Texture"
    bl_idname = "VAT_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VAT'
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.vat_props
        
        # Object info
        obj = context.active_object
        if obj and obj.type == 'MESH':
            box = layout.box()
            box.label(text=f"Active Object: {obj.name}")
            box.label(text=f"Vertices: {len(obj.data.vertices)}")
        else:
            layout.label(text="Select a mesh object", icon='ERROR')
        
        # Settings
        layout.separator()
        layout.prop(props, "export_path")
        layout.prop(props, "texture_name")
        
        layout.separator()
        layout.label(text="Frame Range:")
        row = layout.row(align=True)
        row.prop(props, "start_frame")
        row.prop(props, "end_frame")
        
        layout.separator()
        layout.prop(props, "texture_width")
        layout.operator("vat.calculate_texture_size", icon='BORDERMOVE')
        
        layout.separator()
        layout.prop(props, "export_normals")
        layout.prop(props, "normalize_bounds")
        
        # Export button
        layout.separator()
        layout.operator("vat.export", icon='EXPORT', text="Export VAT")


# Registration
classes = (
    VAT_Properties,
    VAT_OT_Calculate_Texture_Size,
    VAT_OT_Export,
    VAT_PT_Panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vat_props = bpy.props.PointerProperty(type=VAT_Properties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.vat_props

if __name__ == "__main__":
    register()