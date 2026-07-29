import type { SVGProps } from "react";

export type IconName =
  | "activity"
  | "arrowLeft"
  | "arrowRight"
  | "check"
  | "chevronDown"
  | "circleAlert"
  | "clock"
  | "code"
  | "compare"
  | "document"
  | "download"
  | "evaluation"
  | "external"
  | "file"
  | "filter"
  | "flask"
  | "grid"
  | "info"
  | "layers"
  | "logout"
  | "maximize"
  | "menu"
  | "more"
  | "parser"
  | "pause"
  | "play"
  | "plus"
  | "refresh"
  | "search"
  | "settings"
  | "sparkle"
  | "stop"
  | "tasks"
  | "upload"
  | "user"
  | "x";

const paths: Record<IconName, React.ReactNode> = {
  activity: <path d="M3 12h4l2.2-6 4.2 12 2.1-6H21" />,
  arrowLeft: <path d="m15 18-6-6 6-6" />,
  arrowRight: <path d="m9 18 6-6-6-6" />,
  check: <path d="m5 12 4 4L19 6" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  circleAlert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5M12 16h.01" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  code: <path d="m8 9-3 3 3 3m8-6 3 3-3 3m-5 3 2-12" />,
  compare: (
    <>
      <path d="M8 5H4v14h4M16 5h4v14h-4" />
      <path d="m10 9 2-2 2 2m-4 6 2 2 2-2" />
    </>
  ),
  document: (
    <>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v5h4M9 13h6M9 17h5" />
    </>
  ),
  download: <path d="M12 3v12m-4-4 4 4 4-4M5 20h14" />,
  evaluation: (
    <>
      <path d="M5 20V10M12 20V4M19 20v-7" />
      <path d="M3 20h18" />
    </>
  ),
  external: <path d="M14 4h6v6m0-6-9 9M19 14v5H5V5h5" />,
  file: (
    <>
      <path d="M7 3h7l4 4v14H7z" />
      <path d="M14 3v5h4" />
    </>
  ),
  filter: <path d="M4 5h16l-6 7v5l-4 2v-7z" />,
  flask: (
    <>
      <path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3" />
      <path d="M8 15h8" />
    </>
  ),
  grid: (
    <>
      <rect x="4" y="4" width="6" height="6" rx="1" />
      <rect x="14" y="4" width="6" height="6" rx="1" />
      <rect x="4" y="14" width="6" height="6" rx="1" />
      <rect x="14" y="14" width="6" height="6" rx="1" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  layers: <path d="m12 3 9 5-9 5-9-5zm-7 9 7 4 7-4M5 16l7 4 7-4" />,
  logout: <path d="M10 5H5v14h5m4-4 4-3-4-3m4 3H9" />,
  maximize: <path d="M8 3H3v5m13-5h5v5M8 21H3v-5m13 5h5v-5" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  more: (
    <>
      <circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  parser: (
    <>
      <rect x="4" y="4" width="16" height="6" rx="2" />
      <rect x="4" y="14" width="16" height="6" rx="2" />
      <path d="M8 7h.01M8 17h.01M12 7h5M12 17h5" />
    </>
  ),
  pause: <path d="M9 5v14M15 5v14" />,
  play: <path d="m8 5 11 7-11 7z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: <path d="M20 7v5h-5M4 17v-5h5m10.5-4A8 8 0 0 0 6 6l-2 6m.5 4A8 8 0 0 0 18 18l2-6" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 4 4" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19 13.5v-3l-2-.7-.7-1.7.9-1.9-2.1-2.1-1.9.9-1.7-.7L10.5 2h-3l-.7 2-1.7.7-1.9-.9-2.1 2.1.9 1.9-.7 1.7-2 .7v3l2 .7.7 1.7-.9 1.9 2.1 2.1 1.9-.9 1.7.7.7 2h3l.7-2 1.7-.7 1.9.9 2.1-2.1-.9-1.9.7-1.7z" transform="translate(2.5 0) scale(.8)" />
    </>
  ),
  sparkle: <path d="m12 3 1.4 4.6L18 9l-4.6 1.4L12 15l-1.4-4.6L6 9l4.6-1.4zM19 15l.7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7z" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  tasks: (
    <>
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="m3.5 6 1 1 2-2m-3 7 1 1 2-2m-3 7 1 1 2-2" />
    </>
  ),
  upload: <path d="M12 16V4m-4 4 4-4 4 4M5 20h14" />,
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  x: <path d="m6 6 12 12M18 6 6 18" />,
};

export function Icon({
  name,
  size = 18,
  ...props
}: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
