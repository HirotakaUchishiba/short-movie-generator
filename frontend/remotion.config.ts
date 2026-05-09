import { Config } from "@remotion/cli/config";

// Remotion CLI / bundler 設定。
// 既存 frontend (= Vite) と分離されたエントリポイントを持つ。

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setEntryPoint("./remotion/index.ts");

// 並列度。compositor_remotion.py の REMOTION_CONCURRENCY と整合させる。
Config.setConcurrency(4);

// h264 エンコード設定 (= 既存 ffmpeg compositor の crf 18 と整合)
Config.setCodec("h264");
Config.setCrf(18);

// 出力解像度は Composition 側で 1080x1920 を持つので不要だが、念のためデフォルト
Config.setPixelFormat("yuv420p");
