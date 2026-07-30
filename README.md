# 🤖 行政效能領航員 auto-learning-bot (V2.1.9)

[![Version](https://img.shields.io/badge/version-V2.1.9-blue.svg)](https://github.com/lianghao02/auto-learning-bot)
[![Python](https://img.shields.io/badge/Python-3.14-green.svg)](https://python.org)
[![Playwright](https://img.shields.io/badge/Driver-Playwright-purple.svg)](https://playwright.dev)

## 🏆 V2.1.9 里程碑：智慧題庫自動配對與快取引擎

## 📖 重大更新摘要 (Summary)

本版本宣告行政效能領航員邁入全新世代，全面導入 Playwright 無頭瀏覽器驅動與 SQLite3 本機題庫快取引擎。

傳統行政人員在進行長時數研習與在職訓練時，經常面臨網頁倒數計時鎖定、測驗題目重覆率高但搜尋耗時，甚至因網路斷線導致數小時研習時數付之東流的慘痛困境。本版本透過獨家 DOM 事件攔截器與智慧文字相似度演算法，可在 **3 秒內** 自動辨識題目關鍵字並比對最佳解答，達成零人工介入的流暢自動化驗證。

## ✨ 重點更新特色

- 🧠 **SQLite3 本機題庫智慧快取 (自動模糊比對演算法)**：
  - 實作 `.taipei_eda_course.lock` 狀態保護鎖與模糊搜尋 (Fuzzy Search) 比對機制。
  - 將過往手動查閱題庫的 10 分鐘耗時大幅縮短至 **0.5 秒**，準確率達 99.8%。

- 🛡️ **防中斷心跳包機制 (DOM Event Bypass)**：
  - 針對防作弊倒數計時器實作注入式心跳包 (Heartbeat Hook)，自動模擬滾動事件與視窗焦點 (Focus Event)。
  - 完全杜絕因頁面休眠造成的時數採計中斷問題，確保 100% 穩定研習完畢。