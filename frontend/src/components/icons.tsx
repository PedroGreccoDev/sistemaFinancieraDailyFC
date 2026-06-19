import type { CSSProperties } from 'react'

/* Iconos stroke (estilo lucide), inline, sin dependencia. Heredan currentColor. */

type P = { size?: number; style?: CSSProperties; strokeWidth?: number }

const base = (size: number, sw: number) => ({
  width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: sw, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
})

export function IconHome({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M3 9.5 12 3l9 6.5" /><path d="M5 10v10h14V10" /></svg>)
}
export function IconWallet({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><rect x="3" y="6" width="18" height="14" rx="2" /><path d="M3 10h18" /><circle cx="16.5" cy="14" r="1.2" fill="currentColor" stroke="none" /></svg>)
}
export function IconUsers({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><circle cx="9" cy="8" r="3" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" /><path d="M16 4.5a3 3 0 0 1 0 7" /><path d="M21 20c0-2.5-1.5-4.7-3.5-5.6" /></svg>)
}
export function IconReceipt({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M5 3v18l2-1.2L9 21l2-1.2L13 21l2-1.2L17 21l2-1.2V3l-2 1.2L15 3l-2 1.2L11 3 9 4.2 7 3 5 4.2Z" /><path d="M8 8h8M8 12h8" /></svg>)
}
export function IconChart({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M3 3v18h18" /><rect x="7" y="11" width="3" height="6" /><rect x="12.5" y="7" width="3" height="10" /><rect x="18" y="13" width="3" height="4" /></svg>)
}
export function IconExchange({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M4 8h13l-3-3" /><path d="M20 16H7l3 3" /></svg>)
}
export function IconPlus({ size = 16, style, strokeWidth = 2.4 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M12 5v14M5 12h14" /></svg>)
}
export function IconRefresh({ size = 15, style, strokeWidth = 2.2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 4v4h-4" /></svg>)
}
export function IconCheck({ size = 18, style, strokeWidth = 2.4 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M20 6 9 17l-5-5" /></svg>)
}
export function IconAlert({ size = 18, style, strokeWidth = 2.2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.5v.01" /></svg>)
}
export function IconCamera({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z" /><circle cx="12" cy="13" r="3.2" /></svg>)
}
export function IconDownload({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M12 3v12" /><path d="m7 11 5 5 5-5" /><path d="M5 21h14" /></svg>)
}
export function IconShare({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="m8.2 10.8 7.6-3.6M8.2 13.2l7.6 3.6" /></svg>)
}
export function IconClose({ size = 18, style, strokeWidth = 2.2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M6 6l12 12M18 6 6 18" /></svg>)
}
export function IconBanknote({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><rect x="2" y="6" width="20" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /><path d="M5.5 9.5v.01M18.5 14.5v.01" /></svg>)
}
export function IconSettings({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>)
}
export function IconUpload({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>)
}
export function IconFileJson({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><path d="M10 13c0 1-1.5 2-1.5 2s1.5 1 1.5 2M14 13c0 1 1.5 2 1.5 2S14 17 14 19M12 13v6" /></svg>)
}
export function IconTable({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M3 15h18M9 3v18" /></svg>)
}
export function IconLogout({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></svg>)
}
export function IconUserCog({ size = 18, style, strokeWidth = 2 }: P) {
  return (<svg {...base(size, strokeWidth)} style={style}><circle cx="9" cy="8" r="3" /><path d="M3 20c0-3.3 2.7-6 6-6c1 0 1.9.2 2.8.6" /><circle cx="18" cy="16" r="2.4" /><path d="M18 12.5v1M18 18.5v1M21 16h-1M16 16h-1M20.1 13.9l-.7.7M16.6 17.4l-.7.7M20.1 18.1l-.7-.7M16.6 14.6l-.7-.7" /></svg>)
}
