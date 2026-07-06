"""Olasılık hesaplama v8 - Dixon-Coles low-score düzeltmesi + joint İY/MS + veri bazlı rho"""
import math
import logging

logger = logging.getLogger(__name__)

def poi(lam:float,k:int)->float:
    if lam<=0:return 1.0 if k==0 else 0.0
    try:return(lam**k)*math.exp(-lam)/math.factorial(k)
    except(OverflowError,ValueError):return 0.0

def estimate_rho(matches:list)->float:
    """
    Geçmiş maçlardan Dixon-Coles rho parametresini tahmin et.
    Düşük skorlu maçların (0-0, 1-1) Poisson'dan sapmasını ölçer.
    Tipik futbol değeri: -0.13 ile -0.03 arası.
    """
    if len(matches)<30:return -0.05
    n=len(matches)
    lam=sum(m.get("hs",0) for m in matches)/n
    mu=sum(m.get("as",0) for m in matches)/n
    if lam<=0 or mu<=0:return -0.05

    n00=sum(1 for m in matches if m.get("hs")==0 and m.get("as")==0)
    n11=sum(1 for m in matches if m.get("hs")==1 and m.get("as")==1)

    p00_poi=math.exp(-(lam+mu))   # P(0-0) Poisson
    p11_poi=lam*mu*math.exp(-(lam+mu))  # P(1-1) Poisson

    obs00=n00/n
    obs11=n11/n

    # rho'yu 0-0 ve 1-1 fazlalığından/azlığından tahmin et
    # DC düzeltmesi: p00_dc = p00_poi*(1 - lam*mu*rho)
    # => rho = (1 - obs00/p00_poi) / (lam*mu)
    estimates=[]
    if p00_poi>0.001:
        r0=-(obs00/p00_poi-1)/(lam*mu) if lam*mu>0 else -0.05
        estimates.append(r0)
    if p11_poi>0.001:
        # p11_dc = p11_poi*(1 - rho)  => rho = 1 - obs11/p11_poi
        r1=1-(obs11/p11_poi) if obs11>0 else -0.05
        estimates.append(r1)

    if not estimates:return -0.05
    rho_est=sum(estimates)/len(estimates)
    return round(max(-0.20,min(0.0,rho_est)),4)

def dixon_coles_rho(h:int,a:int,lam:float,mu:float,rho:float=-0.05)->float:
    """
    Dixon-Coles düzeltmesi: düşük skorlu sonuçlar (0-0, 1-0, 0-1, 1-1)
    gerçek hayatta Poisson'dan farklı dağılır. rho parametresi bunu düzeltir.
    rho < 0: beraberlik hafifçe azalır, 1-0/0-1 hafifçe artar (tipik futbol)
    """
    if h==0 and a==0:return 1-lam*mu*rho
    elif h==1 and a==0:return 1+mu*rho
    elif h==0 and a==1:return 1+lam*rho
    elif h==1 and a==1:return 1-rho
    return 1.0

def match_probs(hxg:float,axg:float,avg_corner:float=10.0,avg_goals:float=2.75,neutral:bool=False,rho:float=-0.05,rating_diff:float=0.0)->dict:
    if neutral:tot=hxg+axg;hxg=axg=tot/2
    hxg=max(hxg,0.1);axg=max(axg,0.1)

    # Büyük rating farkı → rho sıfıra yaklaşır (güçlü takım maçlarında DC düzeltmesi azalır)
    # 400 puan fark = tam sıfır, 0 puan fark = rho değişmez
    if rating_diff != 0.0:
        rho_scale = max(0.0, 1.0 - abs(rating_diff) / 400.0)
        rho = rho * rho_scale

    MG=7
    
    # Ham Poisson matrisi
    raw_mx=[[poi(hxg,i)*poi(axg,j) for j in range(MG+1)] for i in range(MG+1)]
    
    # Dixon-Coles düzeltmesi (veri bazlı veya varsayılan rho)
    mx=[[raw_mx[i][j]*dixon_coles_rho(i,j,hxg,axg,rho) for j in range(MG+1)] for i in range(MG+1)]
    
    # Normalize (toplam = 1.0)
    total=sum(mx[i][j] for i in range(MG+1) for j in range(MG+1))
    if total>0:
        for i in range(MG+1):
            for j in range(MG+1):
                mx[i][j]/=total
    
    hw=dr=aw=o25=u25=o15=u15=o35=u35=by=bn=0.0
    cs={}
    for i in range(MG+1):
        for j in range(MG+1):
            p=mx[i][j]
            if i>j:hw+=p
            elif i==j:dr+=p
            else:aw+=p
            t=i+j
            if t>=3:o25+=p
            else:u25+=p
            if t>=2:o15+=p
            else:u15+=p
            if t>=4:o35+=p
            else:u35+=p
            if i>0 and j>0:by+=p
            else:bn+=p
            cs[f"{i}-{j}"]=round(p,5)
    
    dc1x=hw+dr;dcx2=dr+aw;dc12=hw+aw
    
    # ─── İY/MS Joint Model ───
    # İlk yarı ve tam maç bağımsız DEĞİL.
    # İlk yarıda önde olan takım ikinci yarıda savunmaya çekilebilir.
    # Yaklaşım: her skor senaryosu için ilk yarı olasılığını hesapla,
    # sonra koşullu olarak maç sonucunu türet.
    hht=hxg*0.42;aht=axg*0.42  # ilk yarı gollerinin oranı (~%42)
    sht=hxg*0.58;sat=axg*0.58  # ikinci yarı
    
    # İlk yarı olasılıkları
    ht_h=ht_d=ht_a=0.0
    ht_mx={}
    for i in range(5):
        for j in range(5):
            p=poi(hht,i)*poi(aht,j)
            if i>j:ht_h+=p
            elif i==j:ht_d+=p
            else:ht_a+=p
            ht_mx[(i,j)]=p
    ht_tot=ht_h+ht_d+ht_a
    if ht_tot>0:ht_h/=ht_tot;ht_d/=ht_tot;ht_a/=ht_tot
    
    # İY/MS joint: P(İY=x, MS=y) hesabı
    # Her ilk yarı skoru için, ikinci yarıda eklenen gollerle tam skor oluştur
    iyms={}
    iy_labels={
        (1,1):"1/1",(1,0):"1/X",(1,-1):"1/2",
        (0,1):"X/1",(0,0):"X/X",(0,-1):"X/2",
        (-1,1):"2/1",(-1,0):"2/X",(-1,-1):"2/2"
    }
    for label in iy_labels.values():iyms[label]=0.0
    
    for(hi,ai),ht_p in ht_mx.items():
        ht_p_norm=ht_p/ht_tot if ht_tot>0 else 0
        if hi>ai:ht_sign=1
        elif hi==ai:ht_sign=0
        else:ht_sign=-1
        
        # İkinci yarı gol olasılıkları
        for h2 in range(5):
            for a2 in range(5):
                sh_p=poi(sht,h2)*poi(sat,a2)
                full_h=hi+h2;full_a=ai+a2
                if full_h>full_a:ms_sign=1
                elif full_h==full_a:ms_sign=0
                else:ms_sign=-1
                
                key=(ht_sign,ms_sign)
                if key in iy_labels:
                    iyms[iy_labels[key]]+=ht_p_norm*sh_p
    
    # Normalize İY/MS
    iy_total=sum(iyms.values())
    if iy_total>0:
        for k in iyms:iyms[k]=round(iyms[k]/iy_total*1.0,4)  # toplam ~1.0 olmalı
    
    # ─── Korner (experimental) ───
    cf=(hxg+axg)/avg_goals if avg_goals>0 else 1.0
    exp_c=max(avg_corner*cf,1.0)
    co85=sum(poi(exp_c,k) for k in range(9,35));cu85=1-co85
    co95=sum(poi(exp_c,k) for k in range(10,35));cu95=1-co95
    co105=sum(poi(exp_c,k) for k in range(11,35));cu105=1-co105
    co115=sum(poi(exp_c,k) for k in range(12,35));cu115=1-co115
    
    top_scores=sorted(cs.items(),key=lambda x:x[1],reverse=True)[:10]
    
    return{
        "home_win":round(hw,4),"draw":round(dr,4),"away_win":round(aw,4),
        "over25":round(o25,4),"under25":round(u25,4),
        "over15":round(o15,4),"under15":round(u15,4),
        "over35":round(o35,4),"under35":round(u35,4),
        "btts_yes":round(by,4),"btts_no":round(bn,4),
        "dc_1x":round(dc1x,4),"dc_x2":round(dcx2,4),"dc_12":round(dc12,4),
        "ht_home":round(ht_h,4),"ht_draw":round(ht_d,4),"ht_away":round(ht_a,4),
        "iy_ms":iyms,"top_scores":top_scores,
        "corners_expected":round(exp_c,1),
        "corner_o85":round(co85,4),"corner_u85":round(cu85,4),
        "corner_o95":round(co95,4),"corner_u95":round(cu95,4),
        "corner_o105":round(co105,4),"corner_u105":round(cu105,4),
        "corner_o115":round(co115,4),"corner_u115":round(cu115,4),
    }
