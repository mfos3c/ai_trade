# ai_trade — $1 altı Binance Futures sinyal + analiz botu

15 dakikalık grafikte, fiyatı **1 USDT altındaki** Binance Futures coinlerini tarar;
kapsamlı teknik indikatör seti **+ MiniMax M3 AI analizi** ile **LONG/SHORT** sinyali üretir
ve **$10 sanal bakiyeyle (paper trading)** işlemleri simüle edip analiz raporu çıkarır.

> ⚠️ **Gerçek para riski yoktur.** Bot Binance'e emir göndermez — sadece public market
> verisi okur ve işlemleri yerel olarak simüle eder. Eğitim/analiz amaçlıdır, yatırım
> tavsiyesi değildir.

## Nasıl çalışır

```
$1 altı coinleri tara ──► 15dk mumları çek ──► İNDİKATÖRLER ──┐
(hacim filtresi)                              EMA9/21/50      │
                                              RSI, MACD       ├─► ağırlıklı skor
                                              Bollinger       │     (-1..+1)
                                              Stochastic      │        │
                                              ADX/+DI/-DI     │        ▼
                                              Hacim ──────────┘   MiniMax M3 AI
                                                                   (LONG/SHORT/NEUTRAL)
                                                                        │
                                                          ai_weight ile birleştir
                                                                        ▼
                                                          NİHAİ KARAR + güven %
                                                                        │
                                              $10 paper trader: pozisyon aç/kapat,
                                              ATR tabanlı SL/TP, PnL, win-rate, rapor
```

## Kurulum

```bash
cd ai_trade
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # MiniMax anahtarını gir (opsiyonel)
```

`.env` içinde `MINIMAX_API_KEY` boş bırakılırsa bot **sadece teknik analizle** çalışır.

## Çalıştırma

```bash
# Tek tarama (modül olarak)
python -m scalpbot.main

# AI'sız (sadece TA)
python -m scalpbot.main --no-ai

# Sürekli loop (her 15dk'da bir tarar)
python -m scalpbot.main --loop

# Tüm açık paper pozisyonları kapat
python -m scalpbot.main --close-all
```

`./run.sh` aynı işi venv'i otomatik kurarak yapar.

## Dashboard (web arayüzü)

Kullanıcı dostu, otomatik yenilenen koyu temalı bir panel:

```bash
./dashboard.sh                      # http://127.0.0.1:8000
./dashboard.sh --port 8080          # farklı port
```

Gösterdikleri:
- **Portföy kartları:** bakiye, ROI, win-rate, toplam PnL, işlem sayısı
- **Aktif sinyaller:** coin, yön (LONG yeşil / SHORT kırmızı), güven çubuğu, fiyat, AI kararı + gerekçe
- **Açık pozisyonlar:** giriş / stop / hedef / marjin / kaldıraç
- **Kapanan işlemler:** TP/SL sonucu ve PnL
- **⟳ Tara** butonu paneli kapatmadan yeni tarama tetikler; "AI" rozeti MiniMax'ın açık/kapalı olduğunu gösterir.

Panel 5 saniyede bir `data/signals.json` ve `data/state.json` dosyalarını okur; bu yüzden
arka planda `./run.sh --loop` çalışırken panel canlı güncellenir.

## Ayarlar — `config.yaml`

| Bölüm | Anahtar | Açıklama |
|-------|---------|----------|
| `market` | `max_price` | Üst fiyat filtresi (varsayılan 1.0 USDT) |
| | `timeframe` | Analiz periyodu (`15m`) |
| | `min_quote_volume` | İlliksit coinleri elemek için 24s hacim eşiği |
| | `max_symbols` | Bir taramada işlenecek max coin |
| `strategy` | `weights` | Her indikatörün skora ağırlığı |
| | `min_confidence` | Bu güvenin altındaki sinyaller elenir |
| | `ai_weight` | TA ↔ AI dengesi (0=sadece TA, 1=sadece AI) |
| | `require_ai_agreement` | AI ile TA aynı yönde değilse sinyali iptal et |
| `risk` | `start_balance` | Başlangıç bakiyesi ($10) |
| | `leverage` | Kaldıraç |
| | `risk_fraction` | İşlem başına bakiyenin yüzdesi (marjin) |
| | `atr_sl_mult` / `risk_reward` | ATR tabanlı SL ve TP mesafesi |

## Çıktılar (`data/`)

- `state.json` — bakiye, açık pozisyonlar, kapanan işlemler (kalıcı durum)
- `report.md` — güncel sinyaller, portföy, açık/kapalı işlem tabloları
- `trades.csv` — tüm kapanan işlemler (analiz için)

## İndikatörler

EMA(9/21/50) trend dizilimi · RSI(14) · MACD(12/26/9) histogram & kesişim ·
Bollinger(20,2) bant konumu · Stochastic(14,3) · ADX(14) + DI yönü (trend gücü filtresi) ·
ATR(14) (SL/TP boyutlama) · Hacim/Hacim-SMA teyidi.

Her indikatör −1..+1 arası oy verir, `config.yaml`'daki ağırlıklarla birleşir.
ADX trend gücü zayıfsa yön teyidi verilmez (yatay piyasada yanlış sinyali azaltır).

## MiniMax M3

`scalpbot/minimax.py` indikatör özetini MiniMax M3'e gönderip JSON yön kararı ister
(`LONG/SHORT/NEUTRAL` + güven + gerekçe). Endpoint/model `.env`'den değiştirilebilir.
Kota tasarrufu için AI yalnızca TA bir yön gösterdiğinde çağrılır.
