import { useEffect, useRef, useState } from "react";

const FONT_LINK_ID = "fc-precision-fonts";
if (typeof document !== "undefined" && !document.getElementById(FONT_LINK_ID)) {
  const link = document.createElement("link");
  link.id = FONT_LINK_ID;
  link.rel = "stylesheet";
  link.href =
    "https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Manrope:wght@400;500;600;700&display=swap";
  document.head.appendChild(link);
}

const RESPONSIVE_STYLE_ID = "fc-card-responsive";
if (typeof document !== "undefined" && !document.getElementById(RESPONSIVE_STYLE_ID)) {
  const style = document.createElement("style");
  style.id = RESPONSIVE_STYLE_ID;
  style.textContent = `
    @media (max-width: 639px) {
      .fc-card-body        { padding: 0.75rem 0.9rem !important; }
      .fc-card-num         { font-size: clamp(1.5rem, 8.5vw, 2.4rem) !important; overflow-wrap: anywhere; min-width: 0; }
      .fc-card-numrow      { min-width: 0; }
      .fc-card-prefix      { font-size: 1rem !important; margin-bottom: 0.3rem !important; }
      .fc-card-title       { font-size: 0.62rem !important; white-space: normal !important; overflow: visible !important; text-overflow: clip !important; max-width: none !important; }
      .fc-card-subtitle    { font-size: 0.7rem !important; }
      .fc-card-header      { margin-bottom: 0.35rem !important; }
      .fc-card-numrow      { margin-bottom: 0.35rem !important; }
      .fc-card-divider     { margin-bottom: 0.35rem !important; }
    }
  `;
  document.head.appendChild(style);
}

interface FinanceDashboardCardProps {
  title: string;
  value: number;
  prefix?: string;
  suffix?: string;
  trend?: number;
  trendLabel?: string;
  accentColor?: string;
  formatValue?: (v: number) => string;
  subtitle?: string;
  onClick?: () => void;
}

function useCountUp(target: number, duration = 300) {
  const [current, setCurrent] = useState(0);
  const raf = useRef<number>(0);

  useEffect(() => {
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 4);
      setCurrent(Math.round(eased * target));
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);

  return current;
}

export function FinanceDashboardCard({
  title,
  value,
  prefix = "",
  suffix = "",
  trend,
  trendLabel,
  accentColor = "#6366f1",
  formatValue,
  subtitle,
  onClick,
}: FinanceDashboardCardProps) {
  const animated = useCountUp(value);
  const display = formatValue
    ? formatValue(animated)
    : animated.toLocaleString("es-AR");

  const up = trend !== undefined && trend >= 0;

  return (
    <div
      className="relative overflow-hidden group"
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}
      style={{
        background: "var(--surface-grad)",
        borderLeft: `2px solid ${accentColor}`,
        borderRadius: "var(--r-lg)",
        boxShadow: `var(--shadow-card), inset 0 1px 0 var(--ov-004)`,
        transition: "box-shadow 0.3s ease, transform 0.3s ease",
        fontFamily: "'Manrope', sans-serif",
        cursor: onClick ? "pointer" : undefined,
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = `var(--shadow-card-hover), 0 0 0 1px ${accentColor}30, inset 0 1px 0 var(--bd-006)`;
        (e.currentTarget as HTMLDivElement).style.transform = "translateY(-2px)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = `var(--shadow-card), inset 0 1px 0 var(--ov-004)`;
        (e.currentTarget as HTMLDivElement).style.transform = "translateY(0)";
      }}
    >
      {/* Diagonal hatching */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.025]"
        style={{
          backgroundImage: `repeating-linear-gradient(
            -45deg, transparent, transparent 8px,
            var(--hatch) 8px, var(--hatch) 9px
          )`,
        }}
      />
      {/* Radial glow */}
      <div
        className="absolute -top-8 -left-8 w-40 h-40 pointer-events-none"
        style={{ background: `radial-gradient(circle, ${accentColor}18 0%, transparent 70%)` }}
      />

      <div className="fc-card-body relative" style={{ padding: "1.25rem 1.4rem" }}>
        {/* Header */}
        <div className="fc-card-header flex items-start justify-between" style={{ marginBottom: "0.6rem" }}>
          <div>
            <p className="fc-card-title" style={{
              fontFamily: "'Manrope', sans-serif",
              fontSize: "0.75rem",
              fontWeight: 700,
              letterSpacing: "0.13em",
              textTransform: "uppercase",
              color: accentColor,
              opacity: 0.95,
              lineHeight: 1.25,
              maxWidth: "calc(100% - 1.25rem)",
            }}>
              {title}
            </p>
            {subtitle && (
              <p className="fc-card-subtitle" style={{
                fontFamily: "'Manrope', sans-serif",
                fontSize: "0.82rem",
                fontWeight: 500,
                color: "rgba(148,163,184,0.7)",
                marginTop: "3px",
              }}>
                {subtitle}
              </p>
            )}
          </div>
          <div className="relative" style={{ marginTop: "3px" }}>
            <div className="w-2 h-2 rounded-full" style={{ background: accentColor }} />
            <div className="absolute inset-0 rounded-full animate-ping" style={{ background: accentColor, opacity: 0.4 }} />
          </div>
        </div>

        {/* Big number — Bebas Neue */}
        <div className="fc-card-numrow flex items-end gap-1.5" style={{ marginBottom: "0.6rem" }}>
          {prefix && (
            <span className="fc-card-prefix" style={{
              fontFamily: "'Bebas Neue', sans-serif",
              fontSize: "1.6rem",
              color: "var(--num-prefix)",
              letterSpacing: "0.04em",
              marginBottom: "0.5rem",
            }}>
              {prefix}
            </span>
          )}
          <span className="fc-card-num" style={{
            fontFamily: "'Bebas Neue', sans-serif",
            fontSize: "4rem",
            lineHeight: 1,
            color: "var(--text-strong)",
            letterSpacing: "0.02em",
            textShadow: `0 0 40px ${accentColor}25`,
          }}>
            {display}
          </span>
          {suffix && (
            <span style={{
              fontFamily: "'Manrope', sans-serif",
              fontSize: "0.8rem",
              fontWeight: 600,
              color: "rgba(148,163,184,0.5)",
              marginBottom: "0.5rem",
              letterSpacing: "0.04em",
            }}>
              {suffix}
            </span>
          )}
        </div>

        {/* Divider */}
        <div className="fc-card-divider" style={{
          height: "1px",
          marginBottom: "0.6rem",
          background: `linear-gradient(to right, ${accentColor}35, var(--ov-004) 60%, transparent)`,
        }} />

        {/* Trend */}
        {trend !== undefined ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5" style={{
              padding: "3px 8px",
              fontFamily: "'Manrope', sans-serif",
              fontSize: "0.75rem",
              fontWeight: 700,
              color: up ? "#4ade80" : "#f87171",
              background: up ? "rgba(74,222,128,0.08)" : "rgba(248,113,113,0.08)",
              border: `1px solid ${up ? "rgba(74,222,128,0.25)" : "rgba(248,113,113,0.25)"}`,
            }}>
              <svg width="8" height="8" viewBox="0 0 8 8" fill="currentColor"
                style={{ transform: up ? "rotate(0deg)" : "rotate(180deg)" }}>
                <polygon points="4,0 8,8 0,8" />
              </svg>
              {up ? "+" : ""}{trend.toFixed(1)}%
            </div>
            {trendLabel && (
              <span style={{
                fontFamily: "'Manrope', sans-serif",
                fontSize: "0.72rem",
                fontWeight: 500,
                color: "rgba(100,116,139,0.9)",
              }}>
                {trendLabel}
              </span>
            )}
          </div>
        ) : (
          <div style={{ height: "22px" }} />
        )}
      </div>

      <div className="absolute bottom-0 left-0 right-0" style={{
        height: "1px",
        background: `linear-gradient(to right, ${accentColor}35, transparent)`,
      }} />
    </div>
  );
}
