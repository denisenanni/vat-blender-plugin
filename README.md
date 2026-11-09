# Vertex Animation Texture (VAT) Exporter for Blender

Bake any mesh animation (armatures, shape keys, modifiers, cloth, object motion) into
textures, and play it back in a game engine with a cheap vertex shader. Unreal Engine 5
is the first supported target.

## What it exports

For an object named in **Name** (default `VAT`):

| File | Contents |
|---|---|
| `VAT_offset.exr` | 32-bit float RGB: per-vertex **offset from the rest pose**, per frame, already in the target engine's axes and units |
| `VAT_normal.exr` | 32-bit float RGB: per-vertex normal (−1..1, not remapped), per frame |
| `VAT_mesh.fbx` | The rest mesh (first baked frame) with an extra UV map, `VAT_Lookup` |
| `VAT_metadata.json` | Frame count, fps, texture size, `frame_v_stride`, offset bounds |

**Why a mesh and a lookup UV?** Engines split and reorder vertices on import (at UV seams
and hard edges), so a shader can't use the vertex ID to find its texel. `VAT_Lookup`
stores each vertex's texel coordinates, and it survives import.

### Texture layout

- Each frame is a block of `rows_per_frame` rows. Vertices fill a row left to right and
  wrap onto the next row past **Max Width**, so any vertex count works.
- Frame 0 is the **top** block of the image. Frame `f` is `f * frame_v_stride` further down in V.
- Frame 0 is the rest pose, so its offsets are all zero.
- With **Power of 2 Height**, padding rows are added at the bottom.

## Install

Blender 3.6 or newer. Go to *Edit › Preferences › Add-ons › Install from Disk*, pick
`vertex_animation_texture.py`, then enable it. The panel is under *3D View › Sidebar (N) › VAT*.

## Use

1. Select the animated mesh and set **Target** to *Unreal Engine*.
2. Set the frame range, or click **Use Scene Range**.
3. Click **Export VAT**.

The vertex count must stay the same on every frame. Remesh, Decimate, liquid sims and a
subdivision level that changes over time will all fail with a clear error.

## Unreal Engine 5 setup

> ⚠️ This setup has not been verified in Unreal yet. The Blender side has automated tests;
> the Unreal side needs a real test, so report what breaks.

### 1. Import the mesh (`VAT_mesh.fbx`)
- Uniform scale **1.0**. Keep normals as imported.
- In the Static Mesh editor, under *LOD0 › Build Settings*, enable **Use Full Precision UVs**.
  Without it, UVs are stored as half floats and land on the wrong texel on wide textures.
- `VAT_Lookup` is the **last** UV channel. If the mesh had one UV map, it's **UV 1**.
- In *Details › Bounds*, raise **Positive/Negative Bounds Extension** by the
  `offset_max` / `offset_min` values from the metadata, or the mesh will be culled while it moves.

### 2. Import the textures (`VAT_offset.exr`, `VAT_normal.exr`)
- **sRGB**: off.
- **Compression**: *HDR High Precision (RGBA 32F)* if your version has it, otherwise *HDR (RGBA 16F)*.
  16F is fine for small motion but jitters when offsets are large.
- **Filter**: Nearest. **Mip Gen Settings**: NoMipmaps. **Never Stream**: on.

### 3. Material
Add a **Custom** node, set its output type to *CMOT Float 3*, and give it these inputs:
`Tex` (connect a *Texture Object* of `VAT_offset`), `UV` (TexCoord with the lookup
channel index), `Frame`, `FrameCount` and `Stride` (`frame_v_stride` from the metadata).

```hlsl
float f0 = floor(Frame);
float f1 = fmod(f0 + 1.0, FrameCount);   // loop back to the start
float t  = Frame - f0;
float3 a = Texture2DSampleLevel(Tex, TexSampler, UV + float2(0, f0 * Stride), 0).rgb;
float3 b = Texture2DSampleLevel(Tex, TexSampler, UV + float2(0, f1 * Stride), 0).rgb;
return lerp(a, b, t);
```

- **Frame** for a looping clip: `frac(Time * FPS / FrameCount) * FrameCount`, with `FPS` and
  `FrameCount` from the metadata.
- Custom node output → **TransformVector (Local → World)** → **World Position Offset**.
- Normals (optional): run the same Custom node on `VAT_normal`, then *TransformVector
  (Local → World)*, then *Normal*. Untick **Tangent Space Normal** on the material.
- For static, non-looping clips, drop the `fmod` and clamp `Frame` instead.

## Tests

The tests run headless, outside Blender, using the `bpy` wheel:

```sh
python -m venv .venv && .venv/bin/pip install bpy pytest OpenEXR
.venv/bin/python -m pytest tests
```

They bake a deforming, moving mesh, read the EXR back with OpenEXR, re-import the FBX,
sample every vertex through `VAT_Lookup` the way Unreal does, and compare against offsets
computed independently with `mathutils`.

## Known limitations
- Normals are smooth per-vertex normals, so hard edges are softened during animation.
- Only one object per export. Join meshes first.
- Unity and Godot presets aren't there yet. *Raw Blender* exports Blender object-space
  metres for custom pipelines.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
