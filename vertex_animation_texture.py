bl_info = {
    "name": "Vertex Animation Texture Exporter",
    "author": "Denise",
    "version": (1, 0, 3),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > VAT",
    "description": "Export vertex animation as textures for use in game engines",
    "category": "Animation",
}

import bpy
import numpy as np
import os
import json


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
    
    # FIX #4: end_frame min should be 0 to match start_frame
    end_frame: bpy.props.IntProperty(
        name="End Frame",
        description="Last frame to bake",
        default=250,
        min=0
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
    
    # Option for coordinate system conversion
    flip_yz: bpy.props.BoolProperty(
        name="Flip Y/Z (Blender to Unity/Unreal)",
        description="Convert from Blender's Z-up to Y-up coordinate system",
        default=False
    )
    
    # FIX #6: Option to force power of 2 height
    power_of_two_height: bpy.props.BoolProperty(
        name="Power of 2 Height",
        description="Round texture height up to nearest power of 2 (for older GPU compatibility)",
        default=False
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
        
        # Get vertex count from evaluated mesh (after modifiers)
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        vertex_count = len(mesh.vertices)
        obj_eval.to_mesh_clear()
        
        frame_count = context.scene.vat_props.end_frame - context.scene.vat_props.start_frame + 1
        
        # Calculate texture dimensions
        # Width = vertex count, Height = frame count
        # Round up to nearest power of 2 for width
        width = 2 ** (vertex_count - 1).bit_length() if vertex_count > 0 else 1
        
        context.scene.vat_props.texture_width = width
        
        self.report({'INFO'}, f"Texture size: {width}x{frame_count} (Vertices: {vertex_count}, Frames: {frame_count})")
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
        
        # Validate frame range
        if props.start_frame > props.end_frame:
            self.report({'ERROR'}, "Start frame must be less than or equal to end frame")
            return {'CANCELLED'}
        
        # Validate export path - handle unsaved files
        if props.export_path == "//" and not bpy.data.filepath:
            self.report({'ERROR'}, "Please save your .blend file first, or set an absolute export path")
            return {'CANCELLED'}
        
        # Get export path
        export_path = bpy.path.abspath(props.export_path)
        if not export_path or export_path == "":
            self.report({'ERROR'}, "Invalid export path")
            return {'CANCELLED'}
            
        if not os.path.exists(export_path):
            try:
                os.makedirs(export_path)
            except OSError as e:
                self.report({'ERROR'}, f"Cannot create export directory: {e}")
                return {'CANCELLED'}
        
        # FIX #8: Check if object has animation
        has_animation = (
            obj.animation_data is not None or 
            any(mod.type == 'ARMATURE' and mod.object and mod.object.animation_data 
                for mod in obj.modifiers) or
            any(mod.type in {'CLOTH', 'SOFT_BODY', 'FLUID', 'DYNAMIC_PAINT'} 
                for mod in obj.modifiers)
        )
        
        if not has_animation:
            self.report({'WARNING'}, "Object has no animation data. Exporting static mesh across frames.")
        
        # Store original frame
        original_frame = context.scene.frame_current
        
        # FIX #5: Use window manager for progress
        wm = context.window_manager
        
        try:
            # Collect all animation data first (positions and normals)
            all_positions, all_normals, bounds_min, bounds_max, vertex_count = self.collect_animation_data(context, obj, wm)
            
            # Validate vertex count consistency
            if vertex_count == 0:
                self.report({'ERROR'}, "Mesh has no vertices")
                return {'CANCELLED'}
            
            # Warn if texture width is smaller than vertex count
            if props.texture_width < vertex_count:
                self.report({'WARNING'}, f"Texture width ({props.texture_width}) is smaller than vertex count ({vertex_count}). Some vertices will be lost!")
            
            # Export position texture
            self.export_position_texture(context, obj, export_path, all_positions, bounds_min, bounds_max, vertex_count)
            
            # Export normal texture if enabled
            if props.export_normals:
                self.export_normal_texture(context, obj, export_path, all_normals, vertex_count)
            
            # Export metadata (reuse collected bounds)
            self.export_metadata(context, obj, export_path, bounds_min, bounds_max, vertex_count)
            
            self.report({'INFO'}, f"VAT exported successfully to {export_path}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}
        
        finally:
            # Restore original frame
            context.scene.frame_set(original_frame)
        
        return {'FINISHED'}
    
    def get_mesh_data(self, context, obj, frame):
        """Get mesh vertex positions and normals at a specific frame"""
        context.scene.frame_set(frame)
        
        # Force dependency graph update
        context.view_layer.update()
        
        # Apply modifiers to get final mesh
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        
        vertex_count = len(mesh.vertices)
        
        # FIX #1: Proper world matrix transformation using full 4x4 matrix
        world_matrix = obj.matrix_world
        
        # Extract local positions using foreach_get (fast)
        local_positions = np.zeros(vertex_count * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', local_positions)
        local_positions = local_positions.reshape((vertex_count, 3))
        
        # Add homogeneous coordinate (w=1) for proper 4x4 matrix multiplication
        ones = np.ones((vertex_count, 1), dtype=np.float32)
        local_positions_h = np.hstack([local_positions, ones])  # Nx4
        
        # Full 4x4 world matrix transformation
        world_matrix_np = np.array(world_matrix, dtype=np.float32)  # 4x4
        positions_h = local_positions_h @ world_matrix_np.T  # Nx4
        positions = positions_h[:, :3]  # Drop w component
        
        # Extract normals
        local_normals = np.zeros(vertex_count * 3, dtype=np.float32)
        mesh.vertices.foreach_get('normal', local_normals)
        local_normals = local_normals.reshape((vertex_count, 3))
        
        # Transform normals - use inverse transpose of 3x3 for correct normal transformation
        # This handles non-uniform scale correctly
        normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
        normal_matrix_np = np.array(normal_matrix, dtype=np.float32)
        normals = local_normals @ normal_matrix_np.T
        
        # Normalize normals
        norms = np.linalg.norm(normals, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normals = normals / norms
        
        # Optional coordinate system conversion (Blender Z-up to Y-up)
        props = context.scene.vat_props
        if props.flip_yz:
            # Swap Y and Z, negate new Z (old Y)
            positions = positions[:, [0, 2, 1]]
            positions[:, 2] = -positions[:, 2]
            normals = normals[:, [0, 2, 1]]
            normals[:, 2] = -normals[:, 2]
        
        obj_eval.to_mesh_clear()
        
        return positions, normals, vertex_count
    
    def collect_animation_data(self, context, obj, wm):
        """Collect all position and normal data for the animation"""
        props = context.scene.vat_props
        
        all_positions = []
        all_normals = []
        vertex_count = None
        
        frame_count = props.end_frame - props.start_frame + 1
        
        # FIX #5: Progress bar
        wm.progress_begin(0, frame_count)
        
        try:
            for i, frame in enumerate(range(props.start_frame, props.end_frame + 1)):
                positions, normals, current_vertex_count = self.get_mesh_data(context, obj, frame)
                
                # Check for vertex count consistency across frames
                if vertex_count is None:
                    vertex_count = current_vertex_count
                elif current_vertex_count != vertex_count:
                    raise ValueError(
                        f"Vertex count changed during animation! Frame {props.start_frame} has {vertex_count} vertices, "
                        f"but frame {frame} has {current_vertex_count} vertices. "
                        f"VAT requires constant vertex count. Check for modifiers that change topology."
                    )
                
                all_positions.append(positions)
                all_normals.append(normals)
                
                # Update progress
                wm.progress_update(i)
        finally:
            wm.progress_end()
        
        all_positions = np.array(all_positions, dtype=np.float32)
        all_normals = np.array(all_normals, dtype=np.float32)
        
        # Calculate bounds across all frames
        bounds_min = np.min(all_positions, axis=(0, 1))
        bounds_max = np.max(all_positions, axis=(0, 1))
        
        return all_positions, all_normals, bounds_min, bounds_max, vertex_count
    
    def normalize_positions(self, positions, bounds_min, bounds_max):
        """Normalize positions to 0-1 range based on bounds"""
        bounds_range = bounds_max - bounds_min
        # Avoid division by zero
        bounds_range = np.where(bounds_range == 0, 1, bounds_range)
        normalized = (positions - bounds_min) / bounds_range
        return normalized
    
    def get_texture_height(self, context):
        """Calculate texture height, optionally rounded to power of 2"""
        props = context.scene.vat_props
        frame_count = props.end_frame - props.start_frame + 1
        
        # FIX #6: Optional power of 2 height
        if props.power_of_two_height:
            return 2 ** (frame_count - 1).bit_length() if frame_count > 0 else 1
        return frame_count
    
    def export_position_texture(self, context, obj, export_path, all_positions, bounds_min, bounds_max, vertex_count):
        """Export vertex positions as texture"""
        props = context.scene.vat_props
        
        frame_count = props.end_frame - props.start_frame + 1
        
        width = props.texture_width
        height = self.get_texture_height(context)
        
        # Create array to store all positions (height=frames, width=vertices, channels=RGB)
        position_data = np.zeros((height, width, 3), dtype=np.float32)
        
        # Fill position data
        for frame_idx, positions in enumerate(all_positions):
            if props.normalize_bounds:
                positions = self.normalize_positions(positions, bounds_min, bounds_max)
            # If not normalizing, store raw world positions (shader must handle this)
            
            # Store positions in texture (pad with zeros if width > vertex count)
            position_data[frame_idx, :vertex_count] = positions
        
        # Create Blender image
        image_name = f"{props.texture_name}_position"
        
        # Remove existing image if it exists
        if image_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[image_name])
        
        image = bpy.data.images.new(image_name, width=width, height=height, alpha=False, float_buffer=True)
        
        # FIX #3: Set colorspace to Non-Color to prevent gamma correction
        image.colorspace_settings.name = 'Non-Color'
        
        # Blender stores pixels bottom-to-top, so flip the data vertically
        position_data_flipped = np.flipud(position_data)
        
        # Flatten and set pixels (Blender expects RGBA, so we add alpha channel)
        pixels = np.zeros((height, width, 4), dtype=np.float32)
        pixels[:, :, :3] = position_data_flipped
        pixels[:, :, 3] = 1.0  # Alpha
        
        # Use foreach_set for faster pixel assignment (if available in Blender version)
        flat_pixels = pixels.flatten()
        try:
            image.pixels.foreach_set(flat_pixels)
        except AttributeError:
            # Fallback for older Blender versions
            image.pixels = flat_pixels.tolist()
        
        # FIX #10: Remove unnecessary pack() - just mark as dirty
        image.update()
        
        # Save as EXR for 32-bit precision
        image.filepath_raw = os.path.join(export_path, f"{props.texture_name}_position.exr")
        image.file_format = 'OPEN_EXR'
        image.save()
        
        print(f"Position texture exported: {image.filepath_raw}")
        print(f"Bounds: Min={bounds_min}, Max={bounds_max}")
    
    def export_normal_texture(self, context, obj, export_path, all_normals, vertex_count):
        """Export vertex normals as texture"""
        props = context.scene.vat_props
        
        frame_count = props.end_frame - props.start_frame + 1
        
        width = props.texture_width
        height = self.get_texture_height(context)
        
        # Create array for normals
        normal_data = np.zeros((height, width, 3), dtype=np.float32)
        
        # Fill normal data
        for frame_idx, normals in enumerate(all_normals):
            # Normalize normals to 0-1 range (from -1 to 1)
            normals_normalized = (normals + 1.0) / 2.0
            normal_data[frame_idx, :vertex_count] = normals_normalized
        
        # Create Blender image
        image_name = f"{props.texture_name}_normal"
        
        if image_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[image_name])
        
        image = bpy.data.images.new(image_name, width=width, height=height, alpha=False, float_buffer=True)
        
        # FIX #3: Set colorspace to Non-Color
        image.colorspace_settings.name = 'Non-Color'
        
        # Flip vertically for Blender's pixel storage
        normal_data_flipped = np.flipud(normal_data)
        
        # Set pixels
        pixels = np.zeros((height, width, 4), dtype=np.float32)
        pixels[:, :, :3] = normal_data_flipped
        pixels[:, :, 3] = 1.0
        
        flat_pixels = pixels.flatten()
        try:
            image.pixels.foreach_set(flat_pixels)
        except AttributeError:
            image.pixels = flat_pixels.tolist()
        
        # FIX #10: Remove unnecessary pack()
        image.update()
        
        # Save as EXR
        image.filepath_raw = os.path.join(export_path, f"{props.texture_name}_normal.exr")
        image.file_format = 'OPEN_EXR'
        image.save()
        
        print(f"Normal texture exported: {image.filepath_raw}")
    
    def export_metadata(self, context, obj, export_path, bounds_min, bounds_max, vertex_count):
        """Export metadata JSON file"""
        props = context.scene.vat_props
        
        frame_count = props.end_frame - props.start_frame + 1
        texture_height = self.get_texture_height(context)
        
        metadata = {
            "vertex_count": vertex_count,
            "frame_count": frame_count,
            "start_frame": props.start_frame,
            "end_frame": props.end_frame,
            "fps": context.scene.render.fps,
            "texture_width": props.texture_width,
            "texture_height": texture_height,
            "padded_height": texture_height != frame_count,  # FIX #6: Indicate if height was padded
            "bounds_min": bounds_min.tolist(),
            "bounds_max": bounds_max.tolist(),
            "normalize_bounds": props.normalize_bounds,
            "has_normals": props.export_normals,
            "coordinate_system": "y_up" if props.flip_yz else "z_up",
            "object_name": obj.name,
        }
        
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
    
    # FIX #2: Cache vertex count to avoid recalculating on every draw
    _cached_vertex_count = None
    _cached_object_name = None
    _cached_base_vertex_count = None
    
    @classmethod
    def update_cache(cls, context):
        """Update cached vertex count - called less frequently than draw()"""
        obj = context.active_object
        if obj and obj.type == 'MESH':
            if cls._cached_object_name != obj.name:
                try:
                    depsgraph = context.evaluated_depsgraph_get()
                    obj_eval = obj.evaluated_get(depsgraph)
                    mesh = obj_eval.to_mesh()
                    cls._cached_vertex_count = len(mesh.vertices)
                    cls._cached_base_vertex_count = len(obj.data.vertices)
                    obj_eval.to_mesh_clear()
                    cls._cached_object_name = obj.name
                except Exception:
                    cls._cached_vertex_count = None
                    cls._cached_base_vertex_count = None
                    cls._cached_object_name = None
        else:
            cls._cached_vertex_count = None
            cls._cached_base_vertex_count = None
            cls._cached_object_name = None
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.vat_props
        
        # Object info
        obj = context.active_object
        if obj and obj.type == 'MESH':
            # FIX #2: Update cache only when object changes
            VAT_PT_Panel.update_cache(context)
            
            box = layout.box()
            box.label(text=f"Active Object: {obj.name}")
            
            if VAT_PT_Panel._cached_vertex_count is not None:
                vertex_count = VAT_PT_Panel._cached_vertex_count
                base_vertex_count = VAT_PT_Panel._cached_base_vertex_count
                
                box.label(text=f"Vertices: {vertex_count}")
                
                # Show base mesh vertex count if different
                if base_vertex_count != vertex_count:
                    box.label(text=f"(Base mesh: {base_vertex_count})")
                
                # Show warning if texture width doesn't match
                if props.texture_width < vertex_count:
                    box.label(text="Texture too narrow!", icon='ERROR')
                
                # FIX #8: Show animation status
                has_animation = (
                    obj.animation_data is not None or 
                    any(mod.type == 'ARMATURE' and mod.object and mod.object.animation_data 
                        for mod in obj.modifiers)
                )
                if not has_animation:
                    box.label(text="No animation detected", icon='INFO')
            else:
                box.label(text="Cannot evaluate mesh", icon='ERROR')
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
        
        # Show frame count
        frame_count = max(0, props.end_frame - props.start_frame + 1)
        layout.label(text=f"Total frames: {frame_count}")
        
        layout.separator()
        layout.prop(props, "texture_width")
        layout.operator("vat.calculate_texture_size", icon='BORDERMOVE')
        
        # FIX #2: Add button to manually refresh vertex count
        layout.operator("vat.refresh_vertex_count", icon='FILE_REFRESH', text="Refresh Vertex Count")
        
        layout.separator()
        layout.prop(props, "export_normals")
        layout.prop(props, "normalize_bounds")
        layout.prop(props, "flip_yz")
        layout.prop(props, "power_of_two_height")
        
        # Export button
        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("vat.export", icon='EXPORT', text="Export VAT")


class VAT_OT_Refresh_Vertex_Count(bpy.types.Operator):
    """Refresh the cached vertex count"""
    bl_idname = "vat.refresh_vertex_count"
    bl_label = "Refresh Vertex Count"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        # FIX #2: Force cache refresh
        VAT_PT_Panel._cached_object_name = None
        VAT_PT_Panel.update_cache(context)
        
        if VAT_PT_Panel._cached_vertex_count is not None:
            self.report({'INFO'}, f"Vertex count: {VAT_PT_Panel._cached_vertex_count}")
        else:
            self.report({'WARNING'}, "Could not evaluate mesh")
        
        return {'FINISHED'}


# Registration
classes = (
    VAT_Properties,
    VAT_OT_Calculate_Texture_Size,
    VAT_OT_Export,
    VAT_OT_Refresh_Vertex_Count,
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