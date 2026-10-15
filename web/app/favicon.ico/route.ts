const favicon = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="FlexMap">
  <rect width="64" height="64" rx="16" fill="#0d4f3f"/>
  <rect x="15" y="31" width="7" height="19" rx="3.5" fill="#9fe3cf"/>
  <rect x="28.5" y="16" width="7" height="34" rx="3.5" fill="#9fe3cf"/>
  <rect x="42" y="24" width="7" height="26" rx="3.5" fill="#9fe3cf"/>
</svg>
`.trim();

export const dynamic = "force-static";

export function GET() {
  return new Response(favicon, {
    headers: {
      "Cache-Control": "public, max-age=86400",
      "Content-Type": "image/svg+xml; charset=utf-8",
    },
  });
}
