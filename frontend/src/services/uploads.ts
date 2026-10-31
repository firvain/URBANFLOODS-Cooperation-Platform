/**
 * Image uploads (`/api/v1/uploads/*`, verified users). Files are re-encoded to WebP by the
 * backend; alt text is required. Errors arrive as `ApiError`: 413 `uploads.too_large`,
 * 415 `uploads.unsupported_type`, 422 `uploads.invalid_image | uploads.animated |
 * uploads.too_large_pixels` (or `fields.alt_text`), 409 `uploads.daily_limit`, 429; deleting an
 * image still used by content is 409 `uploads.in_use`.
 */
import type { components } from '@/types/api-schema'
import { api } from './api'

export type UploadKind = components['schemas']['UploadKind']

/** Accepted by the backend (it sniffs the real format; this is only a first check). */
export const UPLOAD_ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const

/** `url` is `/static/uploads/YYYY/MM/<uuid>.webp` (same origin). */
export type Upload = components['schemas']['UploadOut']
export type UploadList = components['schemas']['UploadList']
/** An item of `GET /uploads/mine/`, with the content that uses it (`used_in`). */
export type MyUpload = components['schemas']['MyUploadOut']
export type UploadUsage = components['schemas']['UploadUsage']

const BASE = '/api/v1/uploads'

export const uploadsService = {
  uploadImage: (file: File, altText: string, kind: UploadKind = 'image') => {
    const body = new FormData()
    body.append('file', file)
    body.append('alt_text', altText)
    body.append('kind', kind)
    return api<Upload>(`${BASE}/images/`, { method: 'POST', body })
  },

  /** 204; 409 `uploads.in_use` while a post cover or any content body uses it. */
  deleteUpload: (id: number) => api<void>(`${BASE}/${id}`, { method: 'DELETE' }),

  listMine: (params: { skip?: number; limit?: number } = {}) =>
    api<UploadList>(`${BASE}/mine/`, { query: params }),
}
