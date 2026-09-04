# WordPressへのメンバー一覧埋め込み

公開メンバー一覧をWordPress内に表示する場合は、埋め込み専用入口の `public-embed.html` をiframeで読み込みます。

```html
<iframe
  id="fire-member-directory"
  src="https://fire-community-map.example.com/public-embed.html"
  style="width:100%; min-height:900px; border:0; display:block;"
  loading="lazy"
></iframe>
<script>
window.addEventListener('message', event => {
  if (event.data?.type !== 'fire-member-directory-height') return;
  const iframe = document.getElementById('fire-member-directory');
  if (iframe) iframe.style.height = `${event.data.height}px`;
});
</script>
```

`public.html?embed=1` でも同じ埋め込み表示になります。
