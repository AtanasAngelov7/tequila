// InlineMedia — per-MIME-type rendering inside message bubbles (§9.2a)
import { useState } from 'react';
import type { ContentBlock } from '../../types';
import type { FileRecord } from '../../api/files-api';
import { filesApi, mimeCategory } from '../../api/files-api';
import FileCard from './FileCard';
import ImageLightbox from './ImageLightbox';
import MediaViewer from './MediaViewer';
import AudioPlayer from './AudioPlayer';

interface InlineMediaProps {
  blocks: ContentBlock[];
  /** Resolved file records (keyed by file_id) */
  fileMap?: Record<string, FileRecord>;
}

export default function InlineMedia({ blocks, fileMap = {} }: InlineMediaProps) {
  const [lightbox, setLightbox] = useState<{ images: Array<{ src: string; alt?: string }>; idx: number } | null>(null);
  const [viewer, setViewer] = useState<{ type: 'pdf' | 'code'; src: string; filename: string } | null>(null);

  const imageBlocks = blocks.filter(
    (b) => b.type === 'image' || (b.type === 'file_ref' && b.file_id && mimeCategory(fileMap[b.file_id!]?.mime_type ?? '') === 'image'),
  );

  const openLightbox = (fileId: string | null, alt?: string) => {
    const srcs: Array<{ src: string; alt?: string }> = imageBlocks.map((b) => ({
      src: b.type === 'image' ? (b.text ?? '') : filesApi.previewUrl(b.file_id!),
      alt: b.alt_text ?? b.file_id ?? undefined,
    }));
    const clickedSrc = fileId ? filesApi.previewUrl(fileId) : alt;
    const idx = srcs.findIndex((s) => s.src === clickedSrc || s.alt === alt);
    setLightbox({ images: srcs, idx: Math.max(idx, 0) });
  };

  const openViewer = (file: FileRecord) => {
    const cat = mimeCategory(file.mime_type);
    if (cat === 'pdf') {
      setViewer({ type: 'pdf', src: filesApi.downloadUrl(file.file_id), filename: file.filename });
    } else {
      setViewer({ type: 'code', src: filesApi.downloadUrl(file.file_id), filename: file.filename });
    }
  };

  // If only text blocks, render nothing (parent handles text)
  const mediaBlocks = blocks.filter((b) => b.type !== 'text');
  if (mediaBlocks.length === 0) return null;

  // Gather image blocks for multi-image grid
  const imgFileIds = imageBlocks
    .filter((b) => b.type === 'file_ref')
    .map((b) => b.file_id!)
    .filter(Boolean);

  return (
    <>
      {/* Image grid */}
      {imgFileIds.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: imgFileIds.length === 1 ? '1fr' : 'repeat(2, 1fr)',
            gap: 4,
            marginTop: 6,
          }}
        >
          {imgFileIds.slice(0, 4).map((fid, i) => (
            <div key={fid} style={{ position: 'relative' }}>
              <img
                src={filesApi.previewUrl(fid)}
                alt={fileMap[fid]?.filename ?? fid}
                style={{
                  width: '100%',
                  maxWidth: 300,
                  maxHeight: 160,
                  objectFit: 'cover',
                  borderRadius: 4,
                  cursor: 'pointer',
                  display: 'block',
                }}
                onClick={() => openLightbox(fid)}
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
              />
              {i === 3 && imgFileIds.length > 4 && (
                <div
                  onClick={() => openLightbox(fid)}
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'rgba(0,0,0,0.55)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#fff',
                    fontWeight: 600,
                    fontSize: 16,
                    cursor: 'pointer',
                    borderRadius: 4,
                  }}
                >
                  +{imgFileIds.length - 4} more
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Non-image file blocks */}
      {blocks
        .filter((b) => b.type === 'file_ref' && b.file_id && mimeCategory(fileMap[b.file_id!]?.mime_type ?? '') !== 'image')
        .map((b) => {
          const file = b.file_id ? fileMap[b.file_id] : undefined;
          if (!file) return null;
          const cat = mimeCategory(file.mime_type);
          if (cat === 'audio') {
            return (
              <div key={b.file_id} style={{ marginTop: 6 }}>
                <AudioPlayer src={filesApi.downloadUrl(file.file_id)} filename={file.filename} />
              </div>
            );
          }
          return (
            <div key={b.file_id} style={{ marginTop: 6 }}>
              <FileCard file={file} onView={openViewer} compact />
            </div>
          );
        })}

      {/* Lightbox */}
      {lightbox && (
        <ImageLightbox
          images={lightbox.images}
          initialIndex={lightbox.idx}
          onClose={() => setLightbox(null)}
        />
      )}

      {/* Side-panel viewer */}
      {viewer && (
        <MediaViewer
          type={viewer.type}
          src={viewer.src}
          filename={viewer.filename}
          onClose={() => setViewer(null)}
        />
      )}
    </>
  );
}
