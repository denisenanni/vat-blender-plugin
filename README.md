# Vertex Animation Texture (VAT) Blender Plugin

A Blender addon for exporting animated mesh data as textures for use in game engines (Unity, Unreal, Godot) and real-time applications.

## Features

- Export vertex positions as 32-bit EXR textures
- Export vertex normals as separate textures
- Automatic texture size calculation
- Bounding box normalization
- Frame range selection
- Metadata JSON export for shader setup
- Support for modifiers and deformations

## Installation

1. Download `vertex_animation_texture.py`
2. Open Blender
3. Go to Edit > Preferences > Add-ons
4. Click "Install" and select the `.py` file
5. Enable "Animation: Vertex Animation Texture Exporter"

## Usage

### 1. Prepare Your Mesh

- Select the animated mesh object
- Ensure your animation is complete (keyframes, modifiers, etc.)
- The mesh vertex count must remain constant across all frames

### 2. Configure Export Settings

Find the VAT panel in the 3D View sidebar (press `N` key, look for "VAT" tab):

- **Export Path**: Directory where textures will be saved
- **Texture Name**: Base name for output files (e.g., "character")
- **Start Frame / End Frame**: Animation range to bake
- **Texture Width**: Automatically calculated or manually set
- **Export Normals**: Include normal data texture
- **Normalize to Bounds**: Map positions to 0-1 range

### 3. Calculate Texture Size

Click "Calculate Texture Size" to automatically determine optimal dimensions:
- **Width** = Vertex count (rounded to power of 2)
- **Height** = Frame count

### 4. Export

Click "Export VAT" to generate:
- `{name}_position.exr` - Vertex positions (RGB = XYZ)
- `{name}_normal.exr` - Vertex normals (RGB = normalized XYZ)
- `{name}_metadata.json` - Animation data for shader setup

## Output Files

### Position Texture
- Format: 32-bit EXR (float precision)
- Width: Vertex count
- Height: Frame count
- Data: RGB = XYZ position (normalized to 0-1 if enabled)

### Normal Texture
- Format: 32-bit EXR
- Data: RGB = Normal vector (converted from -1,1 to 0,1 range)

### Metadata JSON
```json
{
  "vertex_count": 1024,
  "frame_count": 100,
  "start_frame": 1,
  "end_frame": 100,
  "fps": 24,
  "texture_width": 1024,
  "texture_height": 100,
  "bounds_min": [-1.5, 0.0, -1.0],
  "bounds_max": [1.5, 2.0, 1.0],
  "normalize_bounds": true,
  "has_normals": true
}
```

## Shader Implementation

### Unity HLSL Shader Example

```hlsl
Shader "Custom/VertexAnimationTexture"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _PositionTex ("Position Texture", 2D) = "white" {}
        _NormalTex ("Normal Texture", 2D) = "white" {}
        _AnimationTime ("Animation Time", Float) = 0
        _BoundsMin ("Bounds Min", Vector) = (0,0,0,0)
        _BoundsMax ("Bounds Max", Vector) = (1,1,1,0)
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            
            struct appdata
            {
                float2 uv : TEXCOORD0;
                uint vertexID : SV_VertexID;
            };
            
            struct v2f
            {
                float2 uv : TEXCOORD0;
                float4 vertex : SV_POSITION;
                float3 normal : NORMAL;
            };
            
            sampler2D _MainTex;
            sampler2D _PositionTex;
            sampler2D _NormalTex;
            float _AnimationTime;
            float3 _BoundsMin;
            float3 _BoundsMax;
            
            float4 _PositionTex_TexelSize; // Auto-provided by Unity
            
            v2f vert (appdata v)
            {
                v2f o;
                
                // Calculate UV coordinates for texture lookup
                float frameCount = _PositionTex_TexelSize.w; // Height
                float vertexCount = _PositionTex_TexelSize.z; // Width
                
                // Normalize time to frame index
                float frameIndex = frac(_AnimationTime) * frameCount;
                float frame = floor(frameIndex);
                float nextFrame = (frame + 1) % frameCount;
                float blend = frac(frameIndex);
                
                // UV coordinates
                float u = (v.vertexID + 0.5) / vertexCount;
                float v1 = (frame + 0.5) / frameCount;
                float v2 = (nextFrame + 0.5) / frameCount;
                
                // Sample position textures
                float3 pos1 = tex2Dlod(_PositionTex, float4(u, v1, 0, 0)).rgb;
                float3 pos2 = tex2Dlod(_PositionTex, float4(u, v2, 0, 0)).rgb;
                
                // Interpolate between frames
                float3 position = lerp(pos1, pos2, blend);
                
                // Denormalize position (0-1 back to world space)
                position = position * (_BoundsMax - _BoundsMin) + _BoundsMin;
                
                // Sample normals
                float3 normal1 = tex2Dlod(_NormalTex, float4(u, v1, 0, 0)).rgb;
                float3 normal2 = tex2Dlod(_NormalTex, float4(u, v2, 0, 0)).rgb;
                float3 normal = lerp(normal1, normal2, blend);
                
                // Denormalize normal (0-1 back to -1,1)
                normal = normal * 2.0 - 1.0;
                
                o.vertex = UnityObjectToClipPos(float4(position, 1.0));
                o.normal = UnityObjectToWorldNormal(normal);
                o.uv = v.uv;
                
                return o;
            }
            
            fixed4 frag (v2f i) : SV_Target
            {
                // Simple lighting
                float3 lightDir = normalize(float3(0.5, 1, 0.5));
                float NdotL = max(0, dot(i.normal, lightDir));
                
                fixed4 col = tex2D(_MainTex, i.uv);
                col.rgb *= NdotL * 0.8 + 0.2; // Add ambient
                
                return col;
            }
            ENDCG
        }
    }
}
```

### Unreal Engine Material Setup

1. **Create Material**
   - Add two Texture Sample nodes (Position and Normal textures)
   - Set texture compression to HDR or Vector Displacement

2. **Vertex Shader Setup**
   ```
   VertexID → Divide by VertexCount → U coordinate
   Time → Multiply by FPS → Frac → Multiply by FrameCount → V coordinate
   
   Sample Position Texture at (U, V)
   Denormalize: Position * (BoundsMax - BoundsMin) + BoundsMin
   
   Connect to World Position Offset
   ```

3. **Normal Setup**
   ```
   Sample Normal Texture at (U, V)
   Denormalize: Normal * 2 - 1
   
   Connect to Normal input (World Space)
   ```

### Godot Shader Example

```gdshader
shader_type spatial;

uniform sampler2D position_texture : hint_default_white;
uniform sampler2D normal_texture : hint_default_white;
uniform float animation_time = 0.0;
uniform vec3 bounds_min = vec3(0.0);
uniform vec3 bounds_max = vec3(1.0);
uniform float frame_count = 100.0;

void vertex() {
    // Calculate texture coordinates
    float vertex_count = float(textureSize(position_texture, 0).x);
    float u = (float(VERTEX_ID) + 0.5) / vertex_count;
    
    float frame_index = fract(animation_time) * frame_count;
    float frame = floor(frame_index);
    float next_frame = mod(frame + 1.0, frame_count);
    float blend = fract(frame_index);
    
    float v1 = (frame + 0.5) / frame_count;
    float v2 = (next_frame + 0.5) / frame_count;
    
    // Sample positions
    vec3 pos1 = texture(position_texture, vec2(u, v1)).rgb;
    vec3 pos2 = texture(position_texture, vec2(u, v2)).rgb;
    vec3 position = mix(pos1, pos2, blend);
    
    // Denormalize
    position = position * (bounds_max - bounds_min) + bounds_min;
    
    // Sample normals
    vec3 normal1 = texture(normal_texture, vec2(u, v1)).rgb;
    vec3 normal2 = texture(normal_texture, vec2(u, v2)).rgb;
    vec3 normal = mix(normal1, normal2, blend);
    
    // Denormalize normal
    normal = normal * 2.0 - 1.0;
    
    VERTEX = position;
    NORMAL = normal;
}

void fragment() {
    ALBEDO = vec3(1.0);
}
```

## Tips & Best Practices

1. **Vertex Count**: Keep vertex count as low as possible while maintaining detail
2. **Texture Size**: Use power-of-2 dimensions when possible for better GPU performance
3. **Frame Rate**: Consider reducing frame count by sampling every N frames
4. **Precision**: Use EXR format for maximum precision, or convert to PNG for smaller file size
5. **Compression**: Game engines may apply compression - test with your target platform
6. **Multiple Meshes**: Export each mesh separately if they have different vertex counts

## Troubleshooting

### Mesh appears distorted
- Check that "Normalize to Bounds" is enabled
- Verify bounds_min/max in metadata matches shader constants

### Animation doesn't loop
- Ensure start and end frames create a seamless loop
- Check frame count calculation in shader

### Performance issues
- Reduce texture resolution if possible
- Consider using lower precision formats (16-bit float)
- Cache texture lookups when possible

## Technical Details

### How It Works

1. For each frame in the animation:
   - Evaluate all modifiers and deformations
   - Extract vertex positions in world space
   - Store positions as RGB values in texture row

2. Texture Layout:
   - X-axis: Vertices (one column per vertex)
   - Y-axis: Time/Frames (one row per frame)
   - RGB: XYZ position or normal data

3. Shader Reconstruction:
   - Use vertex ID to find column
   - Use time to find row (with interpolation)
   - Sample texture to get position
   - Denormalize from 0-1 back to world space

## License

MIT License - Free to use in commercial and personal projects

## Credits
