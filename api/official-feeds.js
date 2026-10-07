// 「F研公式」タブ用: 公式サイト(WordPress)・note・YouTube の新着を1つのJSONにまとめて返す。
// ブラウザから各RSSを直接読むとCORSで弾かれるため、サーバー側で取得する。
// Vercelのエッジキャッシュで1時間保持するので、各媒体へのアクセスは多くても1時間に1回程度。

const SITE_API = 'https://firekenkyujo.com/wp-json/wp/v2/posts?per_page=8&_embed=wp:featuredmedia&_fields=title,link,date,_links,_embedded';
const NOTE_RSS = 'https://note.com/firekenkyujo2025/rss';
const YOUTUBE_RSS = 'https://www.youtube.com/feeds/videos.xml?channel_id=UC0I-WGSW2xKIHX1tRuzv6-A';
const YOUTUBE_UPLOADS_PLAYLIST = 'UU0I-WGSW2xKIHX1tRuzv6-A';
const LIMIT = 8;

// YouTubeのフィードは断続的に404/500を返す(体感で6割ほど失敗)ので、短い間隔で多めにリトライする
async function fetchText(url, attempts = 3) {
  let lastError;
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url, {
        headers: { 'User-Agent': 'Mozilla/5.0' },
        signal: AbortSignal.timeout(4000),
      });
      if (res.ok) return await res.text();
      lastError = new Error(`HTTP ${res.status}`);
    } catch (err) {
      lastError = err;
    }
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw lastError;
}

function decodeEntities(text) {
  return text
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'").replace(/&amp;/g, '&')
    .trim();
}

function tagText(block, tag) {
  const m = block.match(new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)</${tag}>`));
  return m ? decodeEntities(m[1]) : '';
}

function blocks(xml, tag) {
  return [...xml.matchAll(new RegExp(`<${tag}(?:\\s[^>]*)?>[\\s\\S]*?</${tag}>`, 'g'))].map(m => m[0]);
}

function toIso(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// 外部由来のURLはhttpsのみ通す(javascript: などをhrefに入れさせない)
function safeUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === 'https:' ? u.toString() : '';
  } catch {
    return '';
  }
}

async function loadSite() {
  const posts = JSON.parse(await fetchText(SITE_API));
  return posts.slice(0, LIMIT).map(p => ({
    title: decodeEntities(String(p.title?.rendered || '')),
    url: safeUrl(p.link),
    date: toIso(p.date + '+09:00'),
    image: safeUrl(p._embedded?.['wp:featuredmedia']?.[0]?.source_url || ''),
  })).filter(p => p.title && p.url);
}

async function loadNote() {
  const xml = await fetchText(NOTE_RSS);
  return blocks(xml, 'item').slice(0, LIMIT).map(item => ({
    title: tagText(item, 'title'),
    url: safeUrl(tagText(item, 'link')),
    date: toIso(tagText(item, 'pubDate')),
    image: safeUrl(tagText(item, 'media:thumbnail')),
  })).filter(p => p.title && p.url);
}

function youtubeItem(videoId, title, date) {
  return {
    title,
    url: `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`,
    videoId: /^[\w-]{6,20}$/.test(videoId) ? videoId : '',
    date: toIso(date),
    image: `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg`,
  };
}

// YouTubeのRSSは断続的に404/500を返して不安定。YOUTUBE_API_KEY がVercelに設定されていれば
// Data APIで確実に取得し、無ければRSSにフォールバックする。
async function loadYoutubeFromApi(key) {
  const url = `https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=${LIMIT}&playlistId=${YOUTUBE_UPLOADS_PLAYLIST}&key=${encodeURIComponent(key)}`;
  const data = JSON.parse(await fetchText(url));
  return (data.items || []).map(item => youtubeItem(
    item.snippet?.resourceId?.videoId || '', item.snippet?.title || '', item.snippet?.publishedAt,
  )).filter(p => p.title && p.videoId);
}

async function loadYoutube() {
  if (process.env.YOUTUBE_API_KEY) return loadYoutubeFromApi(process.env.YOUTUBE_API_KEY);
  const xml = await fetchText(YOUTUBE_RSS, 8);
  return blocks(xml, 'entry').slice(0, LIMIT)
    .map(entry => youtubeItem(tagText(entry, 'yt:videoId'), tagText(entry, 'title'), tagText(entry, 'published')))
    .filter(p => p.title && p.videoId);
}

async function settle(loader) {
  try {
    return { items: await loader(), error: null };
  } catch (err) {
    return { items: [], error: String(err.message || err) };
  }
}

module.exports = async function handler(req, res) {
  const [site, note, youtube] = await Promise.all([settle(loadSite), settle(loadNote), settle(loadYoutube)]);
  // 取得に失敗した媒体があるときは短くキャッシュして、早めに再取得させる
  const allOk = !site.error && !note.error && !youtube.error;
  res.setHeader('Cache-Control', allOk
    ? 'public, s-maxage=3600, stale-while-revalidate=86400'
    : 'public, s-maxage=60, stale-while-revalidate=600');
  res.status(200).json({ fetchedAt: new Date().toISOString(), site, note, youtube });
};

module.exports._test = { tagText, blocks, decodeEntities, safeUrl, loadNote, loadYoutube, loadSite };
