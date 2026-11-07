#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float audioLevel;
    float reveal;
    float activity;
    vec2 viewportSize;
    vec4 accent;
} ubuf;
layout(binding = 1) uniform sampler2D referenceImage;

mat2 rotate(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}
float inside(vec2 uv, vec4 bounds) {
    vec2 feather = max(fwidth(uv), vec2(0.001));
    vec2 lo = smoothstep(bounds.xy, bounds.xy + feather, uv);
    vec2 hi = 1.0 - smoothstep(bounds.zw - feather, bounds.zw, uv);
    return lo.x * lo.y * hi.x * hi.y;
}
vec3 referenceLight(vec2 uv) {
    vec3 c = texture(referenceImage, uv).rgb;
    return c * smoothstep(0.025, 0.13, max(c.r, max(c.g, c.b)));
}
void main() {
    vec2 p = (qt_TexCoord0 - 0.5) * 2.0;
    p.y *= ubuf.viewportSize.y / ubuf.viewportSize.x;
    float t = ubuf.time;
    float a = ubuf.reveal;
    float level = ubuf.audioLevel;
    float r = length(p);
    float angle = atan(p.y, p.x);

    // Reproject the supplied holographic shell, with continuously changing surface motion.
    vec2 shell = rotate(t * 0.035 + 0.055 * sin(t * 0.45)) * p;
    shell *= 1.03 + 0.018 * sin(angle * 3.0 - t * 1.1)
                  + 0.012 * sin(angle * 7.0 + t * 0.7) - level * 0.025;
    vec2 shellUV = shell * 0.5 + 0.5;
    float shellMask = smoothstep(0.49, 0.61, r) * (1.0 - smoothstep(1.0, 1.09, r));
    vec3 light = referenceLight(shellUV) * shellMask * (0.38 + a * 0.95);
    light *= 0.90 + 0.10 * sin(angle * 6.0 - t * 1.3);

    // Antialiased orbital paths: round points, softer trails and no hard pinpricks.
    float pixel = 2.0 / ubuf.viewportSize.x;
    for (int i = 0; i < 3; ++i) {
        float f = float(i);
        mat2 orbitRotation = rotate(f * 1.10 + t * (0.09 + f * 0.023));
        vec2 q = orbitRotation * p;
        float flatten = 0.46 + 0.06 * sin(t * 0.33 + f);
        float radius = 0.86 + f * 0.045;
        vec2 ellipse = q / vec2(1.0, flatten);
        float d = abs(length(ellipse) - radius);
        float line = 1.0 - smoothstep(0.002, 0.002 + fwidth(d) * 1.3, d);
        float theta = t * (0.75 + f * 0.26) - f;
        vec2 point = vec2(cos(theta), sin(theta) * flatten) * radius;
        float distanceToPoint = length(q - point);
        float dotCore = exp(-pow(distanceToPoint / (pixel * 0.9), 2.0));
        float halo = exp(-pow(distanceToPoint / (pixel * 2.8), 2.0));
        float depth = (0.35 + 0.65 * smoothstep(-0.7, 0.8, q.y)) * smoothstep(0.46, 0.63, r);
        light += ubuf.accent.rgb * (line * 0.12 + dotCore * 0.72 + halo * 0.14)
               * depth * (0.20 + a * 0.80);
    }
    float ticks = pow(0.5 + 0.5 * cos(angle * 48.0 + t * 0.25), 12.0);
    light += ubuf.accent.rgb * ticks * exp(-pow((r - 0.94) / (pixel * 0.85), 2.0)) * (0.02 + 0.07 * a);

    // The actual eyes and smile from the reference: no substitute cartoon or M.
    vec2 face = p / (0.62 + a * 0.38);
    face -= vec2(0.009 * sin(t * 0.53) + 0.003 * sin(t * 1.21),
                 0.006 * sin(t * 0.81) + 0.13 * (1.0 - a));
    float blinkPhase = mod(t + 1.6, 6.7);
    float blink = exp(-pow((blinkPhase - 6.25) / 0.095, 2.0));
    float opening = smoothstep(0.22, 0.90, a);
    float lid = max(0.018, opening * (1.0 - 0.96 * blink));
    // One aspect-preserving scale and one reference centre for the entire face.
    // Eyelids pivot at the eyes; the smile keeps the original curve when open.
    float faceScale = 2.62;
    vec2 referenceCentre = vec2(0.5005, 0.5323);
    float eyeCentre = (0.498 - referenceCentre.y) * faceScale;
    vec2 eyeUV = vec2(face.x / faceScale + referenceCentre.x,
                      (face.y - eyeCentre) / (faceScale * lid) + 0.498);
    float eyeMask = inside(eyeUV, vec4(0.338, 0.479, 0.473, 0.522))
                  + inside(eyeUV, vec4(0.527, 0.473, 0.663, 0.522));
    vec3 eyes = referenceLight(eyeUV) * eyeMask;
    float mouthOpen = max(0.02, opening * (1.0 + level * 0.22 + 0.025 * sin(t * 1.7)));
    float mouthCentre = (0.576 - referenceCentre.y) * faceScale;
    vec2 mouthUV = vec2(face.x / faceScale + referenceCentre.x,
                        (face.y - mouthCentre) / (faceScale * mouthOpen) + 0.576);
    vec3 mouth = referenceLight(mouthUV) * inside(mouthUV, vec4(0.444, 0.563, 0.560, 0.592));
    float presence = smoothstep(0.02, 0.34, a);
    light += (eyes * (1.18 + 0.04 * sin(t * 2.3 + face.x * 35.0)) + mouth * 1.65) * presence;

    // Dim inner glass lets the projected eyes read on a bright desktop.
    float shade = (0.10 + a * 0.08) * exp(-r * r * 5.0);
    light *= 1.0 + 0.12 * ubuf.activity;
    float crop = 1.0 - smoothstep(0.965, 1.0, abs(p.x));
    vec3 rgb = (1.0 - exp(-light * 1.20)) * crop;
    float alpha = clamp(max(rgb.r, max(rgb.g, rgb.b)) + shade, 0.0, 1.0);
    fragColor = vec4(rgb, alpha) * ubuf.qt_Opacity;
}
