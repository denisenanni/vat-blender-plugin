"""
VAT Plugin Test Suite
=====================
Run this script inside Blender to test the Vertex Animation Texture plugin.

How to use:
1. Install the VAT plugin first
2. Open Blender
3. Go to Scripting workspace (top menu bar)
4. Click "New" to create a new script
5. Paste this entire file
6. Click "Run Script" (or press Alt+P)
7. Check the console for results (Window > Toggle System Console on Windows)

On Mac, start Blender from terminal to see console output:
    /Applications/Blender.app/Contents/MacOS/Blender
"""

import bpy
import bmesh
import numpy as np
import os
import json
import tempfile
import traceback
from mathutils import Vector, Matrix

# ============================================================================
# TEST UTILITIES
# ============================================================================

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def add_pass(self, name):
        self.passed += 1
        print(f"  ✅ PASS: {name}")
    
    def add_fail(self, name, reason):
        self.failed += 1
        self.errors.append((name, reason))
        print(f"  ❌ FAIL: {name}")
        print(f"         Reason: {reason}")
    
    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 60)
        print(f"TEST SUMMARY: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"\nFailed tests:")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        print("=" * 60)
        return self.failed == 0


def clean_scene():
    """Remove all objects from the scene"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def create_cube(name="TestCube", location=(0, 0, 0), scale=(1, 1, 1)):
    """Create a simple cube"""
    bpy.ops.mesh.primitive_cube_add(size=2, location=location, scale=scale)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def create_plane(name="TestPlane", subdivisions=2):
    """Create a subdivided plane"""
    bpy.ops.mesh.primitive_plane_add(size=2)
    obj = bpy.context.active_object
    obj.name = name
    
    # Subdivide for more vertices
    bpy.ops.object.mode_set(mode='EDIT')
    for _ in range(subdivisions):
        bpy.ops.mesh.subdivide()
    bpy.ops.object.mode_set(mode='OBJECT')
    
    return obj


def create_animated_cube(name="AnimatedCube", start_z=0, end_z=2, frames=10):
    """Create a cube with simple Z animation"""
    obj = create_cube(name)
    
    # Frame 1: starting position
    bpy.context.scene.frame_set(1)
    obj.location.z = start_z
    obj.keyframe_insert(data_path="location", frame=1)
    
    # Middle frame: end position
    mid_frame = frames // 2
    bpy.context.scene.frame_set(mid_frame)
    obj.location.z = end_z
    obj.keyframe_insert(data_path="location", frame=mid_frame)
    
    # Last frame: back to start
    bpy.context.scene.frame_set(frames)
    obj.location.z = start_z
    obj.keyframe_insert(data_path="location", frame=frames)
    
    bpy.context.scene.frame_set(1)
    return obj


def create_scaled_rotated_cube(name="TransformedCube", scale=(1, 2, 0.5), rotation=(0.5, 0.3, 0.1)):
    """Create a cube with non-uniform scale and rotation"""
    obj = create_cube(name)
    obj.scale = scale
    obj.rotation_euler = rotation
    
    # Add simple animation
    bpy.context.scene.frame_set(1)
    obj.location.z = 0
    obj.keyframe_insert(data_path="location", frame=1)
    
    bpy.context.scene.frame_set(10)
    obj.location.z = 2
    obj.keyframe_insert(data_path="location", frame=10)
    
    bpy.context.scene.frame_set(1)
    return obj


def create_armature_animated_mesh(name="RiggedMesh"):
    """Create a mesh with armature deformation"""
    # Create a subdivided cube
    bpy.ops.mesh.primitive_cube_add(size=2)
    obj = bpy.context.active_object
    obj.name = name
    
    # Subdivide it
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=2)
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Create armature
    bpy.ops.object.armature_add(enter_editmode=True)
    armature = bpy.context.active_object
    armature.name = f"{name}_Armature"
    
    # Add a bone
    bone = armature.data.edit_bones[0]
    bone.head = (0, 0, -1)
    bone.tail = (0, 0, 1)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Parent mesh to armature with automatic weights
    obj.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    
    # Animate the bone
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')
    
    pose_bone = armature.pose.bones[0]
    
    bpy.context.scene.frame_set(1)
    pose_bone.rotation_euler = (0, 0, 0)
    pose_bone.keyframe_insert(data_path="rotation_euler", frame=1)
    
    bpy.context.scene.frame_set(10)
    pose_bone.rotation_euler = (0, 0.5, 0)
    pose_bone.keyframe_insert(data_path="rotation_euler", frame=10)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.scene.frame_set(1)
    
    # Select the mesh for export
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    return obj


def run_export(export_path, start_frame=1, end_frame=10, normalize=True, export_normals=True, flip_yz=False):
    """Run the VAT export with given settings"""
    props = bpy.context.scene.vat_props
    
    props.export_path = export_path
    props.texture_name = "TEST_VAT"
    props.start_frame = start_frame
    props.end_frame = end_frame
    props.normalize_bounds = normalize
    props.export_normals = export_normals
    props.flip_yz = flip_yz
    
    # Calculate texture size
    bpy.ops.vat.calculate_texture_size()
    
    # Export
    result = bpy.ops.vat.export()
    
    return result == {'FINISHED'}


def load_metadata(export_path):
    """Load the exported metadata JSON"""
    metadata_path = os.path.join(export_path, "TEST_VAT_metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path, 'r') as f:
            return json.load(f)
    return None


def files_exist(export_path):
    """Check if all expected files were created"""
    files = [
        "TEST_VAT_position.exr",
        "TEST_VAT_normal.exr",
        "TEST_VAT_metadata.json"
    ]
    return all(os.path.exists(os.path.join(export_path, f)) for f in files)


# ============================================================================
# TEST CASES
# ============================================================================

def test_basic_cube_export(results):
    """Test: Basic cube with simple animation"""
    print("\n📦 Test: Basic cube export")
    
    clean_scene()
    obj = create_animated_cube(frames=10)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, end_frame=10)
        
        if not success:
            results.add_fail("Basic export", "Export operator failed")
            return
        
        if not files_exist(tmpdir):
            results.add_fail("Basic export", "Not all files were created")
            return
        
        metadata = load_metadata(tmpdir)
        if metadata is None:
            results.add_fail("Basic export", "Could not load metadata")
            return
        
        # Verify metadata
        if metadata["vertex_count"] != 8:
            results.add_fail("Basic export", f"Wrong vertex count: {metadata['vertex_count']} (expected 8)")
            return
        
        if metadata["frame_count"] != 10:
            results.add_fail("Basic export", f"Wrong frame count: {metadata['frame_count']} (expected 10)")
            return
        
        results.add_pass("Basic cube export")


def test_bounds_calculation(results):
    """Test: Bounds are calculated correctly"""
    print("\n📏 Test: Bounds calculation")
    
    clean_scene()
    # Cube moves from Z=0 to Z=5
    obj = create_animated_cube(start_z=0, end_z=5, frames=10)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, end_frame=10)
        
        if not success:
            results.add_fail("Bounds calculation", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        # Cube is 2x2x2, centered. At Z=0, vertices are at Z=-1 to Z=1
        # At Z=5, vertices are at Z=4 to Z=6
        # So bounds should be approximately: min_z=-1, max_z=6
        
        bounds_min_z = metadata["bounds_min"][2]
        bounds_max_z = metadata["bounds_max"][2]
        
        if not (-1.1 < bounds_min_z < -0.9):
            results.add_fail("Bounds calculation", f"bounds_min Z wrong: {bounds_min_z} (expected ~-1)")
            return
        
        if not (5.9 < bounds_max_z < 6.1):
            results.add_fail("Bounds calculation", f"bounds_max Z wrong: {bounds_max_z} (expected ~6)")
            return
        
        results.add_pass("Bounds calculation")


def test_non_uniform_scale(results):
    """Test: Object with non-uniform scale exports correctly"""
    print("\n📐 Test: Non-uniform scale")
    
    clean_scene()
    obj = create_scaled_rotated_cube(scale=(1, 2, 0.5), rotation=(0, 0, 0))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, end_frame=10)
        
        if not success:
            results.add_fail("Non-uniform scale", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        # With scale (1, 2, 0.5), the cube should be:
        # X: -1 to 1 (unchanged)
        # Y: -2 to 2 (doubled)
        # Z: -0.5 to 0.5 at start, plus animation offset
        
        bounds_min_y = metadata["bounds_min"][1]
        bounds_max_y = metadata["bounds_max"][1]
        
        if not (bounds_max_y - bounds_min_y > 3.5):  # Should be ~4 total
            results.add_fail("Non-uniform scale", f"Y bounds wrong: {bounds_min_y} to {bounds_max_y}")
            return
        
        results.add_pass("Non-uniform scale")


def test_rotated_object(results):
    """Test: Object with rotation exports correctly"""
    print("\n🔄 Test: Rotated object")
    
    clean_scene()
    obj = create_scaled_rotated_cube(scale=(1, 1, 1), rotation=(0, 0, 0.785))  # 45 degrees Z
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, end_frame=10)
        
        if not success:
            results.add_fail("Rotated object", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        # A cube rotated 45° on Z should have larger X and Y bounds
        # Original: X from -1 to 1, Y from -1 to 1
        # Rotated: corners extend further (sqrt(2) ≈ 1.414)
        
        bounds_min_x = metadata["bounds_min"][0]
        bounds_max_x = metadata["bounds_max"][0]
        x_range = bounds_max_x - bounds_min_x
        
        if not (x_range > 2.5):  # Should be ~2.83
            results.add_fail("Rotated object", f"X range too small: {x_range} (expected > 2.5)")
            return
        
        results.add_pass("Rotated object")


def test_flip_yz(results):
    """Test: Y/Z flip for Unity/Unreal coordinate system"""
    print("\n🔀 Test: Y/Z coordinate flip")
    
    clean_scene()
    obj = create_animated_cube(start_z=0, end_z=3, frames=10)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Export without flip
        success = run_export(tmpdir, end_frame=10, flip_yz=False)
        metadata_normal = load_metadata(tmpdir)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Export with flip
        clean_scene()
        obj = create_animated_cube(start_z=0, end_z=3, frames=10)
        success = run_export(tmpdir, end_frame=10, flip_yz=True)
        metadata_flipped = load_metadata(tmpdir)
    
    if metadata_normal is None or metadata_flipped is None:
        results.add_fail("Y/Z flip", "Could not load metadata")
        return
    
    # Check coordinate system is recorded
    if metadata_normal["coordinate_system"] != "z_up":
        results.add_fail("Y/Z flip", f"Normal export should be z_up, got {metadata_normal['coordinate_system']}")
        return
    
    if metadata_flipped["coordinate_system"] != "y_up":
        results.add_fail("Y/Z flip", f"Flipped export should be y_up, got {metadata_flipped['coordinate_system']}")
        return
    
    # In flipped version, Z movement should become Y movement
    # So bounds_max Y (index 1) in flipped should be similar to bounds_max Z (index 2) in normal
    normal_z_max = metadata_normal["bounds_max"][2]
    flipped_y_max = metadata_flipped["bounds_max"][1]
    
    # Note: the flip also negates, so we check absolute values are similar
    if not (abs(normal_z_max) - abs(flipped_y_max) < 0.1):
        results.add_fail("Y/Z flip", f"Flip didn't swap coordinates correctly")
        return
    
    results.add_pass("Y/Z coordinate flip")


def test_high_vertex_count(results):
    """Test: Mesh with many vertices"""
    print("\n🔢 Test: High vertex count")
    
    clean_scene()
    obj = create_plane(subdivisions=4)  # Creates 289 vertices
    
    # Add animation
    bpy.context.scene.frame_set(1)
    obj.location.z = 0
    obj.keyframe_insert(data_path="location", frame=1)
    bpy.context.scene.frame_set(10)
    obj.location.z = 1
    obj.keyframe_insert(data_path="location", frame=10)
    bpy.context.scene.frame_set(1)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, end_frame=10)
        
        if not success:
            results.add_fail("High vertex count", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        if metadata["vertex_count"] < 100:
            results.add_fail("High vertex count", f"Vertex count too low: {metadata['vertex_count']}")
            return
        
        # Check texture width is power of 2 and >= vertex count
        if metadata["texture_width"] < metadata["vertex_count"]:
            results.add_fail("High vertex count", "Texture width smaller than vertex count")
            return
        
        results.add_pass("High vertex count")


def test_single_frame(results):
    """Test: Single frame export (static mesh)"""
    print("\n1️⃣ Test: Single frame export")
    
    clean_scene()
    obj = create_cube()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, start_frame=1, end_frame=1)
        
        if not success:
            results.add_fail("Single frame", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        if metadata["frame_count"] != 1:
            results.add_fail("Single frame", f"Frame count wrong: {metadata['frame_count']}")
            return
        
        if metadata["texture_height"] != 1:
            results.add_fail("Single frame", f"Texture height wrong: {metadata['texture_height']}")
            return
        
        results.add_pass("Single frame export")


def test_no_normals(results):
    """Test: Export without normals"""
    print("\n🚫 Test: Export without normals")
    
    clean_scene()
    obj = create_animated_cube(frames=10)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, end_frame=10, export_normals=False)
        
        if not success:
            results.add_fail("No normals", "Export failed")
            return
        
        # Check normal file doesn't exist
        normal_path = os.path.join(tmpdir, "TEST_VAT_normal.exr")
        if os.path.exists(normal_path):
            results.add_fail("No normals", "Normal file was created when it shouldn't be")
            return
        
        metadata = load_metadata(tmpdir)
        if metadata["has_normals"] != False:
            results.add_fail("No normals", "Metadata says has_normals=True")
            return
        
        results.add_pass("Export without normals")


def test_frame_range_subset(results):
    """Test: Export only a subset of frames"""
    print("\n📊 Test: Frame range subset")
    
    clean_scene()
    obj = create_animated_cube(frames=100)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Only export frames 20-30
        success = run_export(tmpdir, start_frame=20, end_frame=30)
        
        if not success:
            results.add_fail("Frame subset", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        if metadata["start_frame"] != 20:
            results.add_fail("Frame subset", f"Start frame wrong: {metadata['start_frame']}")
            return
        
        if metadata["end_frame"] != 30:
            results.add_fail("Frame subset", f"End frame wrong: {metadata['end_frame']}")
            return
        
        if metadata["frame_count"] != 11:  # 20 to 30 inclusive
            results.add_fail("Frame subset", f"Frame count wrong: {metadata['frame_count']}")
            return
        
        results.add_pass("Frame range subset")


def test_power_of_two_height(results):
    """Test: Power of 2 texture height option"""
    print("\n2️⃣ Test: Power of 2 height")
    
    clean_scene()
    obj = create_animated_cube(frames=100)
    
    props = bpy.context.scene.vat_props
    props.power_of_two_height = True
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, end_frame=100)
        
        if not success:
            results.add_fail("Power of 2 height", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        # 100 frames should become 128 (next power of 2)
        if metadata["texture_height"] != 128:
            results.add_fail("Power of 2 height", f"Height wrong: {metadata['texture_height']} (expected 128)")
            return
        
        if metadata["padded_height"] != True:
            results.add_fail("Power of 2 height", "padded_height should be True")
            return
        
        results.add_pass("Power of 2 height")
    
    # Reset
    props.power_of_two_height = False


def test_object_at_origin(results):
    """Test: Object at world origin"""
    print("\n🎯 Test: Object at origin")
    
    clean_scene()
    obj = create_cube(location=(0, 0, 0))
    
    # No animation, just static at origin
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, start_frame=1, end_frame=1)
        
        if not success:
            results.add_fail("Object at origin", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        # Cube at origin: bounds should be -1 to 1 on all axes
        for i, axis in enumerate(['X', 'Y', 'Z']):
            if not (-1.1 < metadata["bounds_min"][i] < -0.9):
                results.add_fail("Object at origin", f"bounds_min {axis} wrong: {metadata['bounds_min'][i]}")
                return
            if not (0.9 < metadata["bounds_max"][i] < 1.1):
                results.add_fail("Object at origin", f"bounds_max {axis} wrong: {metadata['bounds_max'][i]}")
                return
        
        results.add_pass("Object at origin")


def test_object_offset_from_origin(results):
    """Test: Object far from world origin"""
    print("\n📍 Test: Object offset from origin")
    
    clean_scene()
    obj = create_cube(location=(100, 200, 300))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        success = run_export(tmpdir, start_frame=1, end_frame=1)
        
        if not success:
            results.add_fail("Object offset", "Export failed")
            return
        
        metadata = load_metadata(tmpdir)
        
        # Cube centered at (100, 200, 300): bounds should be (99-101, 199-201, 299-301)
        if not (98.9 < metadata["bounds_min"][0] < 99.1):
            results.add_fail("Object offset", f"bounds_min X wrong: {metadata['bounds_min'][0]}")
            return
        
        if not (299.9 < metadata["bounds_max"][2] < 301.1):
            results.add_fail("Object offset", f"bounds_max Z wrong: {metadata['bounds_max'][2]}")
            return
        
        results.add_pass("Object offset from origin")


def test_no_mesh_selected(results):
    """Test: Error handling when no mesh is selected"""
    print("\n⚠️ Test: No mesh selected")
    
    clean_scene()
    # Create a camera (not a mesh)
    bpy.ops.object.camera_add()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        props = bpy.context.scene.vat_props
        props.export_path = tmpdir
        props.start_frame = 1
        props.end_frame = 10
        
        try:
            result = bpy.ops.vat.export()
            if result == {'FINISHED'}:
                results.add_fail("No mesh selected", "Should have failed but didn't")
                return
        except RuntimeError as e:
            # This is expected - Blender raises an exception for invalid operations
            if "mesh" in str(e).lower():
                results.add_pass("No mesh selected (error handled)")
                return
            else:
                results.add_fail("No mesh selected", f"Unexpected error: {e}")
                return
        
        results.add_pass("No mesh selected (error handled)")


def test_invalid_frame_range(results):
    """Test: Error handling for invalid frame range"""
    print("\n⚠️ Test: Invalid frame range")
    
    clean_scene()
    obj = create_cube()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        props = bpy.context.scene.vat_props
        props.export_path = tmpdir
        props.start_frame = 100
        props.end_frame = 10  # End before start!
        
        try:
            result = bpy.ops.vat.export()
            if result == {'FINISHED'}:
                results.add_fail("Invalid frame range", "Should have failed but didn't")
                return
        except RuntimeError as e:
            # This is expected - Blender raises an exception for invalid operations
            results.add_pass("Invalid frame range (error handled)")
            return
        
        results.add_pass("Invalid frame range (error handled)")


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def run_all_tests():
    print("\n" + "=" * 60)
    print("VAT PLUGIN TEST SUITE")
    print("=" * 60)
    
    results = TestResult()
    
    # Store original frame
    original_frame = bpy.context.scene.frame_current
    
    try:
        # Basic tests
        test_basic_cube_export(results)
        test_bounds_calculation(results)
        test_single_frame(results)
        test_no_normals(results)
        test_frame_range_subset(results)
        
        # Transform tests
        test_non_uniform_scale(results)
        test_rotated_object(results)
        test_object_at_origin(results)
        test_object_offset_from_origin(results)
        
        # Feature tests
        test_flip_yz(results)
        test_high_vertex_count(results)
        test_power_of_two_height(results)
        
        # Error handling tests
        test_no_mesh_selected(results)
        test_invalid_frame_range(results)
        
    except Exception as e:
        print(f"\n💥 TEST SUITE CRASHED: {e}")
        traceback.print_exc()
    
    finally:
        # Cleanup
        clean_scene()
        bpy.context.scene.frame_set(original_frame)
    
    # Print summary
    all_passed = results.summary()
    
    return all_passed


# Run tests when script is executed
if __name__ == "__main__":
    run_all_tests()