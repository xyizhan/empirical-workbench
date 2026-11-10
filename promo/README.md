# 宣传片

用 [Remotion](https://www.remotion.dev/) 以代码编写的 48 秒宣传片，1920×1080 / 30fps。场景在 `src/scenes.tsx`，配色与动效参数在 `src/theme.ts`，`public/` 是网页工作台的真实界面截图（Olist 数据）。

```sh
npm install
npm run studio      # 浏览器中预览与调整
npm run render      # 输出 out/promo.mp4
```

渲染需要 Chrome；若 Remotion 无法下载其自带的浏览器，可加 `--browser-executable` 指向本机 Chrome。
