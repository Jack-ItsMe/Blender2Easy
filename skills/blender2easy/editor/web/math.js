/** Coordinate and timing helpers shared by the viewport and independent tests. */
export const unitScale = units => ({m: 1, cm: 0.01, mm: 0.001}[units] ?? 1);
export const radians = degrees => degrees * Math.PI / 180;
export const degrees = angle => angle * 180 / Math.PI;

// Blender XYZ Euler is Rz * Ry * Rx. Three.js calls this intrinsic order ZYX.
export function blenderQuaternion(rotation) {
  const [x, y, z] = rotation.map(value => radians(value) / 2);
  const [cx, cy, cz] = [Math.cos(x), Math.cos(y), Math.cos(z)];
  const [sx, sy, sz] = [Math.sin(x), Math.sin(y), Math.sin(z)];
  return [sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz,
    cx * cy * sz - sx * sy * cz, cx * cy * cz + sx * sy * sz];
}

export function blenderEuler(quaternion, reference = [0, 0, 0]) {
  const [x, y, z, w] = quaternion;
  const sinY = Math.max(-1, Math.min(1, 2 * (w * y - z * x)));
  let angles;
  if (Math.abs(sinY) > 0.9999999) {
    // Match Three's stable ZYX solution at the Euler singularity.
    angles = [0, Math.asin(sinY), Math.atan2(2 * (w * z - x * y), 1 - 2 * (x * x + z * z))];
  } else {
    angles = [Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)),
      Math.asin(sinY), Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))];
  }
  const canonical = angles.map(degrees);
  const nearest = values => values.map((value, i) => value + 360 * Math.round((reference[i] - value) / 360));
  const a = nearest(canonical);
  const b = nearest([canonical[0] + 180, 180 - canonical[1], canonical[2] + 180]);
  const distance = values => values.reduce((sum, value, i) => sum + (value - reference[i]) ** 2, 0);
  return distance(a) <= distance(b) ? a : b;
}

export function sampleTrack(track, frame) {
  const keys = track.keys;
  if (!keys?.length) return null;
  if (frame <= keys[0].frame) return [...keys[0].value];
  if (frame >= keys[keys.length - 1].frame) return [...keys[keys.length - 1].value];
  let right = 1;
  while (keys[right].frame < frame) right++;
  const a = keys[right - 1], b = keys[right];
  if (frame === b.frame) return [...b.value];
  let t = (frame - a.frame) / (b.frame - a.frame);
  const interpolation = a.interpolation ?? 'BEZIER';
  if (interpolation === 'CONSTANT') t = 0;
  // Browser approximation. Blender AUTO_CLAMPED Bezier handles remain render-authoritative.
  if (interpolation === 'BEZIER') t = t * t * (3 - 2 * t);
  return a.value.map((value, i) => value + (b.value[i] - value) * t);
}

export function nativeFrameSeconds(frame, start, end, fps) {
  return (Math.max(start, Math.min(end, frame)) - start) / Math.max(1, fps);
}

export function cameraProjection(spec, aspect, factor = 1) {
  aspect = Math.max(0.000001, aspect);
  // Blender's AUTO fit uses the longer image dimension; explicit fits retain it.
  const horizontal = spec.sensor_fit === 'HORIZONTAL' || (spec.sensor_fit !== 'VERTICAL' && aspect >= 1);
  const major = (spec.ortho_scale ?? 4.5) * factor;
  const width = horizontal ? major : major * aspect;
  const height = horizontal ? major / aspect : major;
  const sensor = spec.sensor_fit === 'VERTICAL' ? (spec.sensor_height ?? 24) : (spec.sensor_width ?? 36);
  return {width, height, fov: degrees(2 * Math.atan(sensor / (2 * (spec.lens ?? 50) * (horizontal ? aspect : 1))))};
}
