"""Glicko-2 rating sistemi — harici kütüphane kullanılmaz, sadece math modülü.

Başlangıç değerleri: rating=1500, RD=350, volatility=0.06
Her maç tek bir "rating period" olarak işlenir (online update).

Referans: Glickman (2012), "Example of the Glicko-2 system"
"""
import math
import logging

logger = logging.getLogger(__name__)

# ─── Sabitler ─────────────────────────────────────────────────────────────────

INIT_RATING  = 1500.0
INIT_RD      = 350.0
INIT_VOL     = 0.06
TAU          = 0.5     # sistem sabiti (volatilite değişimini kısıtlar; 0.3-1.2 arası tipik)
CONV         = 173.7178  # ölçek dönüştürme katsayısı
EPSILON      = 1e-6    # yakınsama eşiği
MAX_ITER     = 100     # Illinois iterasyon limiti
MIN_RD       = 30.0    # RD alt sınırı (hiç 0'a inmemeli)
MAX_RD       = 350.0   # RD üst sınırı


# ─── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

def _g(phi: float) -> float:
    """Glicko-2 g fonksiyonu: RD'yi olasılık eğrisinin eğimine dönüştürür."""
    return 1.0 / math.sqrt(1.0 + 3.0 * phi ** 2 / (math.pi ** 2))


def _E(mu: float, mu_j: float, phi_j: float) -> float:
    """Beklenen skor (lojistik fonksiyon)."""
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _f(x: float, delta: float, phi: float, v: float, a: float) -> float:
    """Illinois algoritması için f(x) fonksiyonu."""
    ex = math.exp(x)
    denom = phi ** 2 + v + ex
    term1 = ex * (delta ** 2 - denom) / (2.0 * denom ** 2)
    term2 = (x - a) / (TAU ** 2)
    return term1 - term2


def _new_volatility(sigma: float, phi: float, delta: float, v: float) -> float:
    """
    Illinois algoritması ile yeni volatilite hesaplar.
    Δ = tahmin hatası, v = varyans tahmini.
    """
    a = math.log(sigma ** 2)

    # Başlangıç aralığı
    A = a
    if delta ** 2 > phi ** 2 + v:
        B = math.log(delta ** 2 - phi ** 2 - v)
    else:
        k = 1
        while _f(a - k * TAU, delta, phi, v, a) < 0:
            k += 1
            if k > 50:  # sonsuz döngü önlemi
                break
        B = a - k * TAU

    fA = _f(A, delta, phi, v, a)
    fB = _f(B, delta, phi, v, a)

    for _ in range(MAX_ITER):
        if abs(B - A) < EPSILON:
            break
        denom = fB - fA
        if denom == 0:
            break
        C = A + (A - B) * fA / denom
        fC = _f(C, delta, phi, v, a)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2.0
        B, fB = C, fC

    return math.exp(A / 2.0)


# ─── Tek maç güncelleme ───────────────────────────────────────────────────────

def update_glicko2(rating: float, rd: float, vol: float,
                   opp_rating: float, opp_rd: float,
                   score: float) -> tuple:
    """
    Tek maç için Glicko-2 güncellemesi.

    score: 1.0 = kazandı, 0.5 = beraberlik, 0.0 = kaybetti
    Döner: (new_rating, new_rd, new_vol)
    """
    # Glicko-2 ölçeğine dönüştür
    mu    = (rating     - 1500.0) / CONV
    phi   = rd  / CONV
    mu_j  = (opp_rating - 1500.0) / CONV
    phi_j = opp_rd / CONV

    g_j   = _g(phi_j)
    E_val = _E(mu, mu_j, phi_j)

    # Adım 3: tahmini varyans v
    v_inv = g_j ** 2 * E_val * (1.0 - E_val)
    v = 1.0 / v_inv if v_inv > 1e-10 else 1e8

    # Adım 4: tahmin hatası Δ
    delta = v * g_j * (score - E_val)

    # Adım 5: yeni volatilite
    sigma_new = _new_volatility(vol, phi, delta, v)

    # Adım 6: φ*
    phi_star = math.sqrt(phi ** 2 + sigma_new ** 2)

    # Adım 7: yeni φ ve μ
    phi_new = 1.0 / math.sqrt(1.0 / phi_star ** 2 + 1.0 / v)
    mu_new  = mu + phi_new ** 2 * g_j * (score - E_val)

    # Gerçek ölçeğe geri dönüştür
    new_rating = CONV * mu_new + 1500.0
    new_rd     = max(MIN_RD, min(MAX_RD, CONV * phi_new))

    return round(new_rating, 1), round(new_rd, 1), round(sigma_new, 6)


# ─── Ana API ──────────────────────────────────────────────────────────────────

def get_team_ratings(matches: list) -> dict:
    """
    Geçmiş maç sonuçlarından Glicko-2 derecelendirmeleri hesaplar.

    matches: data_fetch.py formatında → [{"ht", "at", "hs", "as", "date"}, ...]
    Döner:
      {team_name: {"rating": float, "rd": float, "vol": float,
                   "trend_last5": float, "n": int}}

    trend_last5: son 5 maçtaki ortalama rating değişimi (pozitif = yükseliş)
    """
    if not matches:
        return {}

    # Kronolojik sırala (date alanı ISO8601)
    sorted_m = sorted(matches, key=lambda m: m.get("date", ""))

    ratings: dict = {}   # team → [rating, rd, vol]
    changes: dict = {}   # team → [rating change list]
    counts:  dict = {}   # team → match count

    def _get(team: str) -> list:
        if team not in ratings:
            ratings[team] = [INIT_RATING, INIT_RD, INIT_VOL]
            changes[team] = []
            counts[team]  = 0
        return ratings[team]

    for m in sorted_m:
        hs, aws = m.get("hs"), m.get("as")
        if hs is None or aws is None:
            continue
        hname, aname = m["ht"], m["at"]

        hr, hrd, hvol = _get(hname)
        ar, ard, avol = _get(aname)

        if hs > aws:
            h_score, a_score = 1.0, 0.0
        elif hs == aws:
            h_score, a_score = 0.5, 0.5
        else:
            h_score, a_score = 0.0, 1.0

        new_hr, new_hrd, new_hvol = update_glicko2(hr, hrd, hvol, ar, ard, h_score)
        new_ar, new_ard, new_avol = update_glicko2(ar, ard, avol, hr, hrd, a_score)

        changes[hname].append(new_hr - hr)
        changes[aname].append(new_ar - ar)
        counts[hname]  += 1
        counts[aname]  += 1

        ratings[hname] = [new_hr, new_hrd, new_hvol]
        ratings[aname] = [new_ar, new_ard, new_avol]

    result = {}
    for team, (r, rd, vol) in ratings.items():
        last5  = changes[team][-5:]
        trend  = round(sum(last5) / len(last5), 2) if last5 else 0.0
        result[team] = {
            "rating":      round(r, 1),
            "rd":          round(rd, 1),
            "vol":         round(vol, 6),
            "trend_last5": trend,
            "n":           counts[team],
        }

    logger.info("glicko2 computed teams=%d matches=%d", len(result), len(sorted_m))
    return result


def elo_normalized(rating: float) -> float:
    """
    Rating'i güç modeli için [0.5, 2.0] aralığında normalize eder.
    1500 → 1.0, 1900 → 2.0, 1100 → 0.5 (sınırlanmış)
    """
    raw = (rating - 1500.0) / 400.0 + 1.0
    return max(0.5, min(2.0, raw))
