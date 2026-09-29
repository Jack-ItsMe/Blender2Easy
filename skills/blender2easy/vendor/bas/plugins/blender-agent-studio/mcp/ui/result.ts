import type {Gallery} from '../viewer';

// Some hosts forward standard content but omit custom tool-result metadata.
// Reuse the inline PNG instead of sending another base64 copy in model context.
export function galleryFromResult(result: { _meta?: Record<string, unknown>; content?: unknown[] }): Gallery | undefined {
 const metadata = result._meta?.['blender/viewer'] as Gallery | undefined;
 if (metadata && Array.isArray(metadata.images) && Array.isArray(metadata.details)) return metadata;
 const images: Gallery['images'] = [];
 let bytes = 0;
 for (const value of result.content ?? []) {
  const item = value as {type?: string; mimeType?: string; data?: string};
  if (item?.type !== 'image' || item.mimeType !== 'image/png' || typeof item.data !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(item.data)) continue;
  bytes += item.data.length;
  if (bytes > 14_000_000 || images.length >= 12) break;
  images.push({label: `Preview ${images.length + 1}`, src: `data:image/png;base64,${item.data}`});
 }
 return images.length ? {title: 'Blender preview', status: 'Ready', images, details: [], notice: ''} : undefined;
}
