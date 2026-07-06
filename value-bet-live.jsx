import { useState, useEffect, useCallback } from "react";
import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, ReferenceLine, BarChart, Bar, Cell,
} from "recharts";

const API_BASE = "http://localhost:2000";
const LEAGUES = {
  PL:{name:"Premier League",flag:"🏴"},PD:{name:"La Liga",flag:"🇪🇸"},
  BL1:{name:"Bundesliga",flag:"🇩🇪"},SA:{name:"Serie A",flag:"🇮🇹"},
  FL1:{name:"Ligue 1",flag:"🇫🇷"},DED:{name:"Eredivisie",flag:"🇳🇱"},
  PPL:{name:"Primeira Liga",flag:"🇵🇹"},
};
const CUPS = {
  CL:{name:"Şampiyonlar Ligi",flag:"⭐"},EL:{name:"Avrupa Ligi",flag:"🟠"},
  UECL:{name:"Konferans Ligi",flag:"🔵"},WC:{name:"Dünya Kupası",flag:"🌍"},
};
const ALL = {...LEAGUES,...CUPS};
const MC_L={"tradable":"İŞLEM","informational":"BİLGİ","experimental":"DENEY","disabled":"KAPALI"};
const MC_C={"tradable":"tg","informational":"tn","experimental":"te","disabled":"td"};

const Badge = ({value}) => {
  const p=(value*100).toFixed(1);
  if(value>0.1) return <span style={{background:"linear-gradient(135deg,#00c853,#00e676)",color:"#003d00",padding:"3px 10px",borderRadius:"20px",fontSize:"10px",fontWeight:700,boxShadow:"0 2px 8px rgba(0,200,83,0.3)"}}>+{p}%</span>;
  if(value>0) return <span style={{background:"linear-gradient(135deg,#ffd600,#ffea00)",color:"#5d4600",padding:"3px 10px",borderRadius:"20px",fontSize:"10px",fontWeight:700}}>+{p}%</span>;
  return <span style={{background:"rgba(255,255,255,0.06)",color:"#777",padding:"3px 10px",borderRadius:"20px",fontSize:"10px",fontWeight:600}}>{p}%</span>;
};
const cc=c=>c>=70?"#00e676":c>=40?"#ffd600":"#ff5252";
const Stat=({l,v,c="#aaa"})=>(
  <div style={{textAlign:"center",padding:"6px 10px",background:"rgba(255,255,255,0.03)",borderRadius:"8px",minWidth:"60px"}}>
    <div style={{fontSize:"8px",color:"#666",marginBottom:"2px"}}>{l}</div>
    <div style={{fontSize:"13px",fontWeight:800,color:c,fontFamily:"'JetBrains Mono',monospace"}}>{v}</div>
  </div>
);
const Panel=({children,title,accent="#42a5f5",extra=null})=>(
  <div style={{background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.06)",borderRadius:"12px",padding:"16px",marginBottom:"12px"}}>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:"12px"}}>
      <div style={{fontSize:"11px",color:accent,letterSpacing:"2px",fontWeight:700}}>{title}</div>
      {extra}
    </div>
    {children}
  </div>
);
const Spinner=()=>(
  <div style={{display:"flex",flexDirection:"column",alignItems:"center",padding:"30px",gap:"8px"}}>
    <div style={{width:"24px",height:"24px",border:"3px solid rgba(255,255,255,0.08)",borderTopColor:"#00e676",borderRadius:"50%",animation:"spin 0.7s linear infinite"}}/>
    <span style={{fontSize:"11px",color:"#888"}}>Yükleniyor...</span>
  </div>
);
const NoData=({msg="Veri yok"})=>(
  <div style={{padding:"24px",textAlign:"center",color:"#555",fontSize:"11px"}}>{msg}</div>
);

// ─── DASHBOARD COMPONENTS ──────────────────────────────────────────────────

function BankrollChart({bt}){
  const history=bt?.bankroll_history||[];
  const mc=bt?.monte_carlo;
  if(!history.length) return <NoData msg="Bankroll verisi yok — önce backtest çalıştır."/>;

  const n=history.length;
  const start=history[0]||1000;
  const chartData=history.map((v,i)=>{
    const t=n>1?i/(n-1):1;
    const p5v=mc?+(start+(mc.p5_final-start)*t).toFixed(0):null;
    const p95v=mc?+(start+(mc.p95_final-start)*t).toFixed(0):null;
    return{
      i,bankroll:+v.toFixed(0),
      ...(mc?{p5:p5v,band:+(p95v-p5v).toFixed(0)}:{}),
    };
  });

  const roi=bt?.roi;
  const roiC=roi>0?"#00e676":roi<0?"#ff5252":"#aaa";

  return(
    <>
      <div style={{display:"flex",gap:"8px",marginBottom:"12px",flexWrap:"wrap"}}>
        <Stat l="ROI" v={roi!=null?`${roi>0?"+":""}${roi.toFixed(1)}%`:"—"} c={roiC}/>
        <Stat l="Yield" v={bt?.yield!=null?`${bt.yield.toFixed(1)}%`:"—"} c={roiC}/>
        <Stat l="Bahis" v={bt?.total_bets??bt?.n_bets??"—"}/>
        <Stat l="MaxDD" v={bt?.max_drawdown!=null?`${bt.max_drawdown.toFixed(1)}%`:"—"} c="#ff9800"/>
        {mc&&<Stat l="P95" v={`${mc.p95_final?.toFixed(0)}₺`} c="#00e676"/>}
        {mc&&<Stat l="P5" v={`${mc.p5_final?.toFixed(0)}₺`} c="#ff5252"/>}
        {mc&&<Stat l="İflas" v={`%${mc.ruin_prob?.toFixed(1)}`} c="#ff9800"/>}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={chartData} margin={{top:4,right:8,left:0,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)"/>
          <XAxis dataKey="i" stroke="#333" tick={{fill:"#555",fontSize:9}} label={{value:"Bahis",fill:"#444",fontSize:9,position:"insideBottomRight",offset:-4}}/>
          <YAxis stroke="#333" tick={{fill:"#555",fontSize:9}} tickFormatter={v=>`${v}₺`} width={56}/>
          <Tooltip contentStyle={{background:"#111",border:"1px solid rgba(255,255,255,0.1)",borderRadius:"8px",fontSize:"11px"}} labelStyle={{color:"#888"}} formatter={(v,n)=>[`${v}₺`,n]}/>
          {mc&&<Area type="monotone" dataKey="p5" stackId="band" stroke="none" fill="transparent" legendType="none"/>}
          {mc&&<Area type="monotone" dataKey="band" stackId="band" stroke="none" fill="rgba(0,200,83,0.10)" name="MC Band (P5–P95)"/>}
          <Line type="monotone" dataKey="bankroll" stroke="#00e676" strokeWidth={2} dot={false} name="Bankroll"/>
        </ComposedChart>
      </ResponsiveContainer>
    </>
  );
}

function CalibrationDiagram({bt}){
  const cal=(bt?.calibration||[]).filter(c=>c.predicted_mid!=null&&c.actual_rate!=null);
  if(!cal.length) return <NoData msg="Kalibrasyon verisi yok."/>;

  const sorted=[...cal].sort((a,b)=>a.predicted_mid-b.predicted_mid);
  const chartData=sorted.map(c=>({
    predicted:+c.predicted_mid.toFixed(3),
    actual:+c.actual_rate.toFixed(3),
    ref:+c.predicted_mid.toFixed(3),  // perfect calibration: y = x
    count:c.count||1,
    market:c.market||"",
  }));

  const CustomDot=({cx,cy,payload})=>{
    if(!cx||!cy) return null;
    const r=Math.min(10,Math.max(4,Math.sqrt((payload.count||1)*4)));
    const diff=payload.actual-payload.predicted;
    const fill=diff>0.05?"#00e676":diff<-0.05?"#ff5252":"#42a5f5";
    return<circle cx={cx} cy={cy} r={r} fill={fill} opacity={0.8} stroke="rgba(255,255,255,0.15)" strokeWidth={1}/>;
  };

  return(
    <>
      <div style={{fontSize:"9px",color:"#666",marginBottom:"8px"}}>Yeşil=iyi kalibre, Kırmızı=zayıf. Nokta boyutu = bahis sayısı.</div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={chartData} margin={{top:4,right:8,left:0,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)"/>
          <XAxis dataKey="predicted" type="number" domain={[0,1]} stroke="#333" tick={{fill:"#555",fontSize:9}} tickFormatter={v=>`${(v*100).toFixed(0)}%`} label={{value:"Tahmin",fill:"#444",fontSize:9,position:"insideBottomRight",offset:-4}}/>
          <YAxis type="number" domain={[0,1]} stroke="#333" tick={{fill:"#555",fontSize:9}} tickFormatter={v=>`${(v*100).toFixed(0)}%`} width={38}/>
          <Tooltip contentStyle={{background:"#111",border:"1px solid rgba(255,255,255,0.1)",borderRadius:"8px",fontSize:"11px"}} formatter={(v,n,p)=>[`${(v*100).toFixed(1)}% (n=${p?.payload?.count})`,n]}/>
          <ReferenceLine y={0} stroke="transparent"/>
          {/* 45° perfect calibration reference */}
          <Line type="linear" dataKey="ref" stroke="rgba(255,255,255,0.18)" strokeWidth={1} strokeDasharray="6 3" dot={false} name="Mükemmel"/>
          {/* Actual calibration dots */}
          <Line type="monotone" dataKey="actual" stroke="transparent" dot={<CustomDot/>} activeDot={false} name="Gerçek"/>
        </ComposedChart>
      </ResponsiveContainer>
    </>
  );
}

function MarketHeatmap({bt}){
  const mp=bt?.market_performance;
  if(!mp||!Object.keys(mp).length) return <NoData msg="Market performans verisi yok."/>;

  const rows=Object.entries(mp)
    .map(([k,v])=>({key:k,roi:v.roi??v.ROI??0,bets:v.bets??v.n_bets??0,hit:v.hit_rate??v.hit??null,yield_:v.yield??null}))
    .sort((a,b)=>b.roi-a.roi);

  const roiColor=(roi)=>{
    if(roi>10) return{bg:"rgba(0,200,83,0.20)",fg:"#00e676"};
    if(roi>3)  return{bg:"rgba(0,200,83,0.10)",fg:"#76e07e"};
    if(roi>0)  return{bg:"rgba(0,200,83,0.06)",fg:"#aaa"};
    if(roi>-3) return{bg:"rgba(255,82,82,0.06)",fg:"#aaa"};
    if(roi>-10)return{bg:"rgba(255,82,82,0.10)",fg:"#ff8a80"};
    return       {bg:"rgba(255,82,82,0.20)",fg:"#ff5252"};
  };

  return(
    <div style={{overflowX:"auto"}}>
      <div style={{display:"grid",gridTemplateColumns:`repeat(${Math.min(rows.length,6)},1fr)`,gap:"4px",minWidth:"400px"}}>
        {rows.map(r=>{
          const {bg,fg}=roiColor(r.roi);
          return(
            <div key={r.key} style={{background:bg,borderRadius:"8px",padding:"8px 6px",textAlign:"center",border:"1px solid rgba(255,255,255,0.06)"}}>
              <div style={{fontSize:"9px",color:"#888",marginBottom:"3px",textTransform:"uppercase",letterSpacing:"0.5px"}}>{r.key}</div>
              <div style={{fontSize:"16px",fontWeight:800,color:fg,fontFamily:"'JetBrains Mono',monospace"}}>{r.roi>0?"+":""}{r.roi.toFixed(1)}<span style={{fontSize:"9px"}}>%</span></div>
              <div style={{fontSize:"9px",color:"#666",marginTop:"2px"}}>{r.bets} bet</div>
              {r.hit!=null&&<div style={{fontSize:"8px",color:"#555"}}>Hit {(r.hit*100).toFixed(0)}%</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EloTable({analyses}){
  const eloMap={};
  for(const a of(analyses||[])){
    if(a.home_elo&&a.home_team) eloMap[a.home_team]={...a.home_elo,team:a.home_team};
    if(a.away_elo&&a.away_team) eloMap[a.away_team]={...a.away_elo,team:a.away_team};
  }
  const rows=Object.values(eloMap).sort((a,b)=>b.rating-a.rating);
  if(!rows.length) return <NoData msg="ELO verisi yok — /analyze yükle."/>;

  const trendIcon=(t)=>{
    if(t>5)  return{icon:"↑",c:"#00e676"};
    if(t<-5) return{icon:"↓",c:"#ff5252"};
    return       {icon:"→",c:"#888"};
  };
  const rdColor=(rd)=>rd<100?"#00e676":rd<200?"#ffd600":"#ff9800";

  return(
    <div style={{overflowX:"auto"}}>
      <table style={{width:"100%",borderCollapse:"separate",borderSpacing:"0 3px",fontSize:"11px",minWidth:"380px"}}>
        <thead>
          <tr style={{color:"#555",fontSize:"9px",letterSpacing:"1px"}}>
            <th style={{textAlign:"left",padding:"4px 8px"}}>#</th>
            <th style={{textAlign:"left",padding:"4px 8px"}}>TAKIM</th>
            <th style={{textAlign:"center",padding:"4px 6px"}}>RATING</th>
            <th style={{textAlign:"center",padding:"4px 6px"}}>RD</th>
            <th style={{textAlign:"center",padding:"4px 6px"}}>TREND</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r,i)=>{
            const {icon,c}=trendIcon(r.trend_last5??0);
            return(
              <tr key={r.team} style={{background:i%2===0?"rgba(255,255,255,0.015)":"transparent"}}>
                <td style={{padding:"6px 8px",color:"#555",fontFamily:"'JetBrains Mono',monospace",fontSize:"10px"}}>{i+1}</td>
                <td style={{padding:"6px 8px",color:"#ccc",fontWeight:600}}>{r.team}</td>
                <td style={{textAlign:"center",padding:"6px",fontFamily:"'JetBrains Mono',monospace",color:"#e0e0e0",fontWeight:700}}>{r.rating?.toFixed(0)}</td>
                <td style={{textAlign:"center",padding:"6px",fontFamily:"'JetBrains Mono',monospace",color:rdColor(r.rd??350),fontSize:"10px"}}>{r.rd?.toFixed(0)}</td>
                <td style={{textAlign:"center",padding:"6px",fontFamily:"'JetBrains Mono',monospace",color:c,fontSize:"14px",fontWeight:800}}>{icon}<span style={{fontSize:"8px",color:"#666",marginLeft:"2px"}}>{(r.trend_last5??0).toFixed(1)}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CLVTrend({clv}){
  const report=clv?.report||[];
  if(!report.length) return <NoData msg="CLV verisi yok — maçlar analiz edildikten sonra oluşur."/>;

  const chartData=[...report]
    .sort((a,b)=>(a.opening_ts||"").localeCompare(b.opening_ts||""))
    .map((r,i)=>({
      i,
      clv:+r.clv_pct.toFixed(2),
      match:`${r.match} [${r.market}]`,
      dir:r.clv_direction,
    }));

  const avg=clv?.avg_clv_percent;
  const pos=clv?.positive_rate;

  const CustomBar=(props)=>{
    const{x,y,width,height,payload}=props;
    if(!height) return null;
    const fill=payload.clv>0?"#00e676":"#ff5252";
    const actualHeight=Math.abs(height);
    const actualY=payload.clv>0?y:y+height;
    return<rect x={x} y={actualY} width={width} height={actualHeight} fill={fill} opacity={0.75} rx={2}/>;
  };

  return(
    <>
      <div style={{display:"flex",gap:"8px",marginBottom:"12px",flexWrap:"wrap"}}>
        {avg!=null&&<Stat l="Ort. CLV" v={`${avg>0?"+":""}${avg.toFixed(1)}%`} c={avg>0?"#00e676":"#ff5252"}/>}
        {pos!=null&&<Stat l="Pozitif" v={`%${pos.toFixed(0)}`} c={pos>50?"#00e676":"#ff9800"}/>}
        <Stat l="Toplam" v={clv?.total_entries??report.length}/>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{top:4,right:8,left:0,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)"/>
          <XAxis dataKey="i" stroke="#333" tick={{fill:"#555",fontSize:8}} label={{value:"Bahis No",fill:"#444",fontSize:9,position:"insideBottomRight",offset:-4}}/>
          <YAxis stroke="#333" tick={{fill:"#555",fontSize:9}} tickFormatter={v=>`${v}%`} width={40}/>
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" strokeWidth={1}/>
          <Tooltip contentStyle={{background:"#111",border:"1px solid rgba(255,255,255,0.1)",borderRadius:"8px",fontSize:"10px"}} formatter={(v,n,p)=>[`${v>0?"+":""}${v}%`,p?.payload?.match]} labelFormatter={()=>""}/>
          <Bar dataKey="clv" shape={<CustomBar/>} name="CLV%">
            {chartData.map((e,i)=><Cell key={i} fill={e.clv>0?"#00e676":"#ff5252"}/>)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {clv?.by_market&&Object.keys(clv.by_market).length>0&&(
        <div style={{display:"flex",gap:"6px",flexWrap:"wrap",marginTop:"10px"}}>
          {Object.entries(clv.by_market).map(([mk,s])=>(
            <div key={mk} style={{background:"rgba(255,255,255,0.03)",borderRadius:"6px",padding:"4px 8px",fontSize:"9px"}}>
              <span style={{color:"#888"}}>{mk}: </span>
              <span style={{color:s.avg_clv_pct>0?"#00e676":"#ff5252",fontWeight:700,fontFamily:"'JetBrains Mono',monospace"}}>{s.avg_clv_pct>0?"+":""}{s.avg_clv_pct?.toFixed(1)}%</span>
              <span style={{color:"#555",marginLeft:"4px"}}>({s.n})</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ─── BACKTEST SUMMARY (Backtest tab) ────────────────────────────────────────

function BacktestSummary({bt}){
  if(!bt) return null;
  const roi=bt.roi??0;
  const roiC=roi>0?"#00e676":"#ff5252";
  const live=bt.live_ready;

  return(
    <div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:"6px",marginBottom:"12px"}}>
        <Stat l="ROI" v={`${roi>0?"+":""}${roi.toFixed(1)}%`} c={roiC}/>
        <Stat l="Yield" v={`${(bt.yield??0).toFixed(1)}%`} c={roiC}/>
        <Stat l="Toplam Bet" v={bt.total_bets??bt.n_bets??"—"}/>
        <Stat l="Max DD" v={`${(bt.max_drawdown??0).toFixed(1)}%`} c="#ff9800"/>
        <Stat l="Brier" v={(bt.brier??0).toFixed(3)} c="#42a5f5"/>
        <Stat l="Oran Modu" v={bt.odds_mode==="real"?"GERÇEK":"SİM"} c={bt.odds_mode==="real"?"#00e676":"#ff9800"}/>
        <Stat l="Live Ready" v={live?"✓ EVET":"✗ HAYIR"} c={live?"#00e676":"#ff5252"}/>
        <Stat l="Kayıp Serisi" v={bt.longest_losing_streak??0} c="#ff9800"/>
      </div>
      {bt.live_ready_reasons?.length>0&&(
        <div style={{fontSize:"10px",color:"#888",background:"rgba(255,255,255,0.02)",borderRadius:"8px",padding:"8px 10px",marginBottom:"10px"}}>
          {bt.live_ready_reasons.map((r,i)=><div key={i}>• {r}</div>)}
        </div>
      )}
      {bt.sensitivity&&(
        <div style={{marginBottom:"12px"}}>
          <div style={{fontSize:"10px",color:"#ffd600",letterSpacing:"1px",fontWeight:700,marginBottom:"6px"}}>HASSASLIK ANALİZİ</div>
          <table style={{width:"100%",borderCollapse:"separate",borderSpacing:"0 3px",fontSize:"11px"}}>
            <thead><tr style={{color:"#555",fontSize:"9px"}}>
              <th style={{textAlign:"left",padding:"3px 8px"}}>Min Edge</th>
              <th style={{textAlign:"center"}}>ROI%</th>
              <th style={{textAlign:"center"}}>Yield%</th>
              <th style={{textAlign:"center"}}>Bet</th>
            </tr></thead>
            <tbody>{bt.sensitivity.map((s,i)=>(
              <tr key={i} style={{background:s.roi>0?"rgba(0,200,83,0.05)":"rgba(255,82,82,0.05)"}}>
                <td style={{padding:"5px 8px",fontFamily:"'JetBrains Mono',monospace",color:"#888"}}>%{(s.min_edge*100).toFixed(0)}</td>
                <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:s.roi>0?"#00e676":"#ff5252",fontWeight:700}}>{s.roi>0?"+":""}{s.roi.toFixed(1)}%</td>
                <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#aaa"}}>{s.yield.toFixed(1)}%</td>
                <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#aaa"}}>{s.n_bets}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {bt.disabled_by_backtest?.length>0&&(
        <div style={{fontSize:"10px",color:"#ff5252",background:"rgba(255,82,82,0.05)",borderRadius:"8px",padding:"8px 10px"}}>
          🚫 Otomatik devre dışı: {bt.disabled_by_backtest.join(", ")}
        </div>
      )}
    </div>
  );
}

// ─── MANUEL ANALİZ TAB ────────────────────────────────────────────────────

const POS_EFFECTS={GK:{def:0.92},CB:{def:0.95},FB:{def:0.97,atk:0.98},CM:{atk:0.97,def:0.97},AM:{atk:0.93},ST:{atk:0.88},WG:{atk:0.91}};
const SEV_MULT={definite_out:1.0,"75pct_out":0.75,doubtful:0.5};

function injuryPreview(pos,sev){
  const s=SEV_MULT[sev]||0.5;
  const e=POS_EFFECTS[pos]||{atk:0.97,def:0.97};
  const atk=e.atk?Math.round((1-e.atk)*s*100):0;
  const def=e.def?Math.round((1-e.def)*s*100):0;
  const parts=[];
  if(atk) parts.push(`Saldırı -%${atk}`);
  if(def) parts.push(`Savunma -%${def}`);
  return parts.length?parts.join(", "):"Etki yok";
}

function parseScores(s){
  return (s||"").split(",").map(x=>x.trim()).filter(Boolean).map(x=>{
    const[a,b]=x.split("-");
    const gf=parseFloat(a),ga=parseFloat(b);
    return(!isNaN(gf)&&!isNaN(ga))?[gf,ga]:null;
  }).filter(Boolean);
}

function ManualTab(){
  const[homeTeam,setHomeTeam]=useState("");
  const[awayTeam,setAwayTeam]=useState("");
  const[homeL10,setHomeL10]=useState("");
  const[awayL10,setAwayL10]=useState("");
  const[homeL5,setHomeL5]=useState("");
  const[awayL5,setAwayL5]=useState("");
  const[odds,setOdds]=useState({home:"",draw:"",away:"",over25:"",under25:""});
  const[injuries,setInjuries]=useState([]);
  const[weather,setWeather]=useState("normal");
  const[importance,setImportance]=useState("normal");
  const[neutralVenue,setNeutralVenue]=useState(false);
  const[homeRest,setHomeRest]=useState(4);
  const[awayRest,setAwayRest]=useState(4);
  const[userEst,setUserEst]=useState({home:"",draw:"",away:""});
  const[ctxOpen,setCtxOpen]=useState(false);
  const[estOpen,setEstOpen]=useState(false);
  const[loading,setLoading]=useState(false);
  const[result,setResult]=useState(null);
  const[error,setError]=useState(null);

  const userTotal=(parseFloat(userEst.home)||0)+(parseFloat(userEst.draw)||0)+(parseFloat(userEst.away)||0);

  const addInj=team=>setInjuries(p=>[...p,{team,player_name:"",position:"ST",injury_type:"hamstring",severity:"definite_out"}]);
  const updInj=(i,f,v)=>setInjuries(p=>p.map((x,j)=>j===i?{...x,[f]:v}:x));
  const delInj=i=>setInjuries(p=>p.filter((_,j)=>j!==i));

  const submit=async()=>{
    setLoading(true);setError(null);setResult(null);
    const payload={
      home_team:homeTeam||"Ev Sahibi",away_team:awayTeam||"Deplasman",
      home_last_10:parseScores(homeL10),away_last_10:parseScores(awayL10),
      home_last_5_home:parseScores(homeL5),away_last_5_away:parseScores(awayL5),
      odds:Object.fromEntries(Object.entries(odds).filter(([,v])=>v&&parseFloat(v)>1).map(([k,v])=>[k,parseFloat(v)])),
      injuries:injuries.filter(x=>x.player_name),
      weather,match_importance:importance,neutral_venue:neutralVenue,
      home_rest_days:parseInt(homeRest)||4,away_rest_days:parseInt(awayRest)||4,
      user_estimate:(userEst.home||userEst.draw||userEst.away)?{
        home_win_pct:parseFloat(userEst.home)||null,
        draw_pct:parseFloat(userEst.draw)||null,
        away_win_pct:parseFloat(userEst.away)||null,
      }:null,
    };
    try{
      const r=await fetch(`${API_BASE}/analyze-manual`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      if(!r.ok) throw new Error(await r.text());
      setResult(await r.json());
    }catch(e){setError(e.message);}
    setLoading(false);
  };

  const inp={background:"rgba(255,255,255,0.04)",border:"1px solid rgba(255,255,255,0.1)",borderRadius:"6px",color:"#e0e0e0",padding:"6px 8px",fontSize:"11px",width:"100%"};
  const sel={...inp,cursor:"pointer"};
  const cardStyle={background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.06)",borderRadius:"10px",padding:"14px",marginBottom:"10px"};
  const label={fontSize:"10px",color:"#888",marginBottom:"4px",display:"block"};

  return(
    <div>
      {/* ── Bölüm 1: Temel Bilgiler ─────────────────────────────────────── */}
      <div style={cardStyle}>
        <div style={{fontSize:"11px",color:"#42a5f5",letterSpacing:"2px",fontWeight:700,marginBottom:"12px"}}>⚽ TEMEL BİLGİLER</div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"10px",marginBottom:"10px"}}>
          <div><label style={label}>Ev Takımı</label><input style={inp} value={homeTeam} onChange={e=>setHomeTeam(e.target.value)} placeholder="Manchester City"/></div>
          <div><label style={label}>Deplasman</label><input style={inp} value={awayTeam} onChange={e=>setAwayTeam(e.target.value)} placeholder="Arsenal"/></div>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"10px",marginBottom:"10px"}}>
          <div><label style={label}>Ev Son 10 Maç (örn: 2-1,1-0,0-2)</label><input style={inp} value={homeL10} onChange={e=>setHomeL10(e.target.value)} placeholder="2-1,1-1,3-0,0-2,1-0"/></div>
          <div><label style={label}>Dep Son 10 Maç</label><input style={inp} value={awayL10} onChange={e=>setAwayL10(e.target.value)} placeholder="1-1,0-0,2-1,1-2,0-1"/></div>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"10px",marginBottom:"12px"}}>
          <div><label style={label}>Ev Son 5 İç Saha</label><input style={inp} value={homeL5} onChange={e=>setHomeL5(e.target.value)} placeholder="2-0,3-1,1-0"/></div>
          <div><label style={label}>Dep Son 5 Deplasman</label><input style={inp} value={awayL5} onChange={e=>setAwayL5(e.target.value)} placeholder="1-1,0-1,2-0"/></div>
        </div>
        <div style={{fontSize:"10px",color:"#888",marginBottom:"8px",letterSpacing:"1px",fontWeight:600}}>ORANLAR (opsiyonel)</div>
        <div style={{display:"flex",gap:"8px",flexWrap:"wrap"}}>
          {[["home","1"],["draw","X"],["away","2"],["over25","Ü2.5"],["under25","A2.5"]].map(([k,lb])=>(
            <div key={k} style={{flex:"1",minWidth:"70px"}}>
              <label style={label}>{lb}</label>
              <input style={inp} type="number" step="0.01" min="1" value={odds[k]} onChange={e=>setOdds(o=>({...o,[k]:e.target.value}))} placeholder="2.10"/>
            </div>
          ))}
        </div>
      </div>

      {/* ── Bölüm 2: Kadro / Sakatlik ───────────────────────────────────── */}
      <div style={cardStyle}>
        <div style={{fontSize:"11px",color:"#ff9800",letterSpacing:"2px",fontWeight:700,marginBottom:"12px"}}>🏥 KADRO / SAKATLIK</div>
        {["home","away"].map(team=>(
          <div key={team} style={{marginBottom:"12px"}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:"8px"}}>
              <span style={{fontSize:"10px",color:"#ccc",fontWeight:600}}>{team==="home"?"🏠 Ev Sahibi":"✈️ Deplasman"}</span>
              <button onClick={()=>addInj(team)} style={{fontSize:"10px",background:"rgba(255,152,0,0.12)",border:"1px solid rgba(255,152,0,0.25)",borderRadius:"6px",color:"#ff9800",padding:"3px 10px",cursor:"pointer"}}>+ Oyuncu Ekle</button>
            </div>
            {injuries.filter((_,i)=>injuries[i].team===team).length===0&&(
              <div style={{fontSize:"10px",color:"#555",padding:"6px 0"}}>Eksik oyuncu yok</div>
            )}
            {injuries.map((inj,i)=>inj.team!==team?null:(
              <div key={i} style={{background:"rgba(255,152,0,0.04)",border:"1px solid rgba(255,152,0,0.12)",borderRadius:"8px",padding:"8px",marginBottom:"6px"}}>
                <div style={{display:"flex",gap:"6px",flexWrap:"wrap",alignItems:"flex-end"}}>
                  <div style={{flex:"2",minWidth:"100px"}}><label style={label}>Oyuncu</label><input style={inp} value={inj.player_name} onChange={e=>updInj(i,"player_name",e.target.value)} placeholder="Salah"/></div>
                  <div style={{flex:"1",minWidth:"70px"}}><label style={label}>Pozisyon</label>
                    <select style={sel} value={inj.position} onChange={e=>updInj(i,"position",e.target.value)}>
                      {["GK","CB","FB","CM","AM","ST","WG"].map(p=><option key={p} value={p}>{p}</option>)}
                    </select>
                  </div>
                  <div style={{flex:"1",minWidth:"90px"}}><label style={label}>Sakatlık</label>
                    <select style={sel} value={inj.injury_type} onChange={e=>updInj(i,"injury_type",e.target.value)}>
                      {[["hamstring","Hamstring"],["knee","Diz"],["ankle","Ayak Bileği"],["suspension","Ceza"],["illness","Hastalık"],["other","Diğer"]].map(([v,l])=><option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                  <div style={{flex:"1",minWidth:"90px"}}><label style={label}>Şiddet</label>
                    <select style={sel} value={inj.severity} onChange={e=>updInj(i,"severity",e.target.value)}>
                      {[["definite_out","Kesin Yok"],["75pct_out","%75 Yok"],["doubtful","Şüpheli"]].map(([v,l])=><option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                  <button onClick={()=>delInj(i)} style={{background:"rgba(255,82,82,0.1)",border:"1px solid rgba(255,82,82,0.2)",borderRadius:"6px",color:"#ff5252",padding:"6px 8px",cursor:"pointer",fontSize:"12px",alignSelf:"flex-end"}}>🗑️</button>
                </div>
                <div style={{fontSize:"9px",color:"#ff9800",marginTop:"5px"}}>⚡ Tahmini etki: {injuryPreview(inj.position,inj.severity)}</div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* ── Bölüm 3: Bağlam (collapsible) ──────────────────────────────── */}
      <div style={cardStyle}>
        <button onClick={()=>setCtxOpen(o=>!o)} style={{width:"100%",background:"none",border:"none",cursor:"pointer",display:"flex",justifyContent:"space-between",alignItems:"center",padding:0}}>
          <span style={{fontSize:"11px",color:"#ce93d8",letterSpacing:"2px",fontWeight:700}}>⚙️ MAÇ BAĞLAMI</span>
          <span style={{color:"#666",fontSize:"14px"}}>{ctxOpen?"▲":"▼"}</span>
        </button>
        {ctxOpen&&(
          <div style={{marginTop:"12px"}}>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"10px",marginBottom:"10px"}}>
              <div><label style={label}>🌤️ Hava Durumu</label>
                <select style={sel} value={weather} onChange={e=>setWeather(e.target.value)}>
                  {[["normal","☀️ Normal"],["rain","🌧️ Yağmur"],["heavy_rain","⛈️ Şiddetli Yağmur"],["wind","💨 Rüzgar"],["snow","❄️ Kar"]].map(([v,l])=><option key={v} value={v}>{l}</option>)}
                </select>
              </div>
              <div><label style={label}>🏆 Maç Önemi</label>
                <select style={sel} value={importance} onChange={e=>setImportance(e.target.value)}>
                  {[["normal","⚽ Normal"],["must_win","🔥 Kazanmak Zorunda"],["cup_final","🏆 Kupa Finali"],["relegation","📉 Küme Düşme"],["derby","⚔️ Derby"]].map(([v,l])=><option key={v} value={v}>{l}</option>)}
                </select>
              </div>
            </div>
            <div style={{display:"flex",gap:"16px",alignItems:"center",flexWrap:"wrap"}}>
              <label style={{display:"flex",alignItems:"center",gap:"6px",cursor:"pointer",fontSize:"11px",color:"#ccc"}}>
                <input type="checkbox" checked={neutralVenue} onChange={e=>setNeutralVenue(e.target.checked)} style={{accentColor:"#ce93d8"}}/>
                Tarafsız Saha
              </label>
              <div style={{display:"flex",alignItems:"center",gap:"8px"}}>
                <span style={{fontSize:"10px",color:"#888"}}>Dinlenme:</span>
                <label style={label}>Ev</label>
                <input type="number" style={{...inp,width:"50px"}} min={1} max={14} value={homeRest} onChange={e=>setHomeRest(e.target.value)}/>
                <span style={{color:"#555",fontSize:"10px"}}>gün</span>
                <label style={label}>Dep</label>
                <input type="number" style={{...inp,width:"50px"}} min={1} max={14} value={awayRest} onChange={e=>setAwayRest(e.target.value)}/>
                <span style={{color:"#555",fontSize:"10px"}}>gün</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Bölüm 4: Kendi Tahminin (collapsible) ───────────────────────── */}
      <div style={cardStyle}>
        <button onClick={()=>setEstOpen(o=>!o)} style={{width:"100%",background:"none",border:"none",cursor:"pointer",display:"flex",justifyContent:"space-between",alignItems:"center",padding:0}}>
          <span style={{fontSize:"11px",color:"#ffd600",letterSpacing:"2px",fontWeight:700}}>🎯 KENDİ TAHMİNİN (opsiyonel)</span>
          <span style={{color:"#666",fontSize:"14px"}}>{estOpen?"▲":"▼"}</span>
        </button>
        {estOpen&&(
          <div style={{marginTop:"12px"}}>
            <div style={{display:"flex",gap:"10px",flexWrap:"wrap",marginBottom:"8px"}}>
              {[["home","Ev Galibiyeti %"],["draw","Beraberlik %"],["away","Dep Galibiyeti %"]].map(([k,lb])=>(
                <div key={k} style={{flex:"1",minWidth:"100px"}}>
                  <label style={label}>{lb}</label>
                  <input type="number" style={inp} min={0} max={100} value={userEst[k]} onChange={e=>setUserEst(u=>({...u,[k]:e.target.value}))} placeholder="33"/>
                </div>
              ))}
            </div>
            {(userEst.home||userEst.draw||userEst.away)&&(
              <div style={{display:"inline-flex",alignItems:"center",gap:"6px",padding:"3px 10px",borderRadius:"12px",fontSize:"10px",fontWeight:700,background:Math.abs(userTotal-100)<=2?"rgba(0,200,83,0.15)":"rgba(255,82,82,0.15)",border:`1px solid ${Math.abs(userTotal-100)<=2?"rgba(0,200,83,0.3)":"rgba(255,82,82,0.3)"}`,color:Math.abs(userTotal-100)<=2?"#00e676":"#ff5252"}}>
                Toplam: {userTotal.toFixed(0)}%{Math.abs(userTotal-100)>2&&" — 100 olmalı"}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Bölüm 5: Analiz Butonu ──────────────────────────────────────── */}
      <button onClick={submit} disabled={loading} style={{width:"100%",padding:"12px",borderRadius:"10px",border:"1px solid rgba(0,200,83,0.4)",background:"rgba(0,200,83,0.15)",color:"#00e676",fontSize:"13px",fontWeight:800,cursor:"pointer",letterSpacing:"1px",marginBottom:"16px"}}>
        {loading?"⏳ Analiz ediliyor...":"🔍 ANALİZ ET"}
      </button>
      {error&&<div style={{padding:"10px",background:"rgba(255,82,82,0.08)",border:"1px solid rgba(255,82,82,0.2)",borderRadius:"8px",color:"#ff5252",fontSize:"11px",marginBottom:"12px"}}>⚠️ {error}</div>}

      {/* ── Bölüm 6: Response ───────────────────────────────────────────── */}
      {result&&(
        <div>
          {/* Temel sonuç özeti */}
          <div style={{...cardStyle,borderColor:"rgba(0,200,83,0.15)"}}>
            <div style={{fontSize:"11px",color:"#00e676",letterSpacing:"2px",fontWeight:700,marginBottom:"10px"}}>
              📊 {result.home_team} vs {result.away_team}
            </div>
            <div style={{display:"flex",gap:"8px",flexWrap:"wrap",marginBottom:"10px"}}>
              <Stat l="xG Ev"   v={result.expected_goals?.home?.toFixed(2)} c="#42a5f5"/>
              <Stat l="xG Dep"  v={result.expected_goals?.away?.toFixed(2)} c="#ff9800"/>
              <Stat l="1"       v={`${(result.probabilities?.home_win*100)?.toFixed(0)}%`}/>
              <Stat l="X"       v={`${(result.probabilities?.draw*100)?.toFixed(0)}%`}/>
              <Stat l="2"       v={`${(result.probabilities?.away_win*100)?.toFixed(0)}%`}/>
              <Stat l="Ü2.5"   v={`${(result.probabilities?.over25*100)?.toFixed(0)}%`} c="#ffd600"/>
              <Stat l="Güven"   v={`${result.confidence}%`} c={cc(result.confidence)}/>
            </div>

            {/* Value betler */}
            {result.value_bets?.length>0&&(
              <div style={{marginBottom:"10px"}}>
                <div style={{fontSize:"9px",color:"#00e676",letterSpacing:"1px",fontWeight:600,marginBottom:"5px"}}>🎯 VALUE BETLER</div>
                {result.value_bets.map((b,i)=>(
                  <div key={i} style={{display:"flex",alignItems:"center",gap:"8px",padding:"5px 8px",background:"rgba(0,200,83,0.06)",borderRadius:"6px",marginBottom:"4px",fontSize:"11px"}}>
                    <span style={{color:"#e0e0e0",fontWeight:600}}>{b.label}</span>
                    <span style={{color:"#aaa"}}>@{b.odds?.toFixed(2)}</span>
                    <Badge value={b.value_pct/100}/>
                    <span style={{color:"#00e676",fontFamily:"'JetBrains Mono',monospace",fontWeight:700}}>{b.bet}₺</span>
                  </div>
                ))}
              </div>
            )}

            {/* Markets tablosu (kompakt) */}
            <table style={{width:"100%",borderCollapse:"separate",borderSpacing:"0 2px",fontSize:"10px"}}>
              <thead><tr style={{color:"#555",fontSize:"8px"}}>
                <th style={{textAlign:"left",padding:"3px 6px"}}>MARKET</th>
                <th style={{textAlign:"center"}}>OLASILIK</th>
                <th style={{textAlign:"center"}}>ADİL ORAN</th>
                <th style={{textAlign:"center"}}>GİRİLEN</th>
                <th style={{textAlign:"center"}}>DEĞER</th>
              </tr></thead>
              <tbody>
                {(result.markets||[]).filter(m=>["home","draw","away","over25","under25"].includes(m.key)).map(m=>(
                  <tr key={m.key} style={{background:m.is_value?"rgba(0,200,83,0.05)":"rgba(255,255,255,0.01)"}}>
                    <td style={{padding:"5px 6px",color:m.is_value?"#e0e0e0":"#888",fontWeight:m.is_value?600:400}}>{m.label}</td>
                    <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:m.is_value?"#00e676":"#999"}}>{m.prob}%</td>
                    <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#555"}}>{m.model_fair_odds?.toFixed(2)}</td>
                    <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#ccc"}}>{m.odds_source==="manual"?m.odds?.toFixed(2):"-"}</td>
                    <td style={{textAlign:"center"}}>{m.is_value?<Badge value={m.value_pct/100}/>:<span style={{color:"#444"}}>-</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* A) Sakatlık Özet Kartı */}
          {result.injury_summary&&(
            <div style={{...cardStyle,borderColor:"rgba(255,152,0,0.2)"}}>
              <div style={{fontSize:"11px",color:"#ff9800",letterSpacing:"2px",fontWeight:700,marginBottom:"10px"}}>🏥 KADRO ETKİSİ</div>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"10px"}}>
                {[["home","Ev"],["away","Dep"]].map(([t,lb])=>{
                  const atk=result.injury_summary[`${t}_atk_mult`];
                  const def=result.injury_summary[`${t}_def_mult`];
                  const out=result.injury_summary[`${t}_players_out`]||[];
                  return(
                    <div key={t} style={{padding:"8px",background:"rgba(255,152,0,0.04)",borderRadius:"8px"}}>
                      <div style={{fontSize:"10px",color:"#ff9800",fontWeight:600,marginBottom:"5px"}}>{lb}</div>
                      <div style={{fontSize:"10px",color:"#aaa"}}>
                        Saldırı: <span style={{color:atk<1?"#ff5252":"#888",fontWeight:700}}>{atk===1?"değişmez":`×${atk}`}</span>
                      </div>
                      <div style={{fontSize:"10px",color:"#aaa"}}>
                        Savunma: <span style={{color:def<1?"#ff5252":"#888",fontWeight:700}}>{def===1?"değişmez":`×${def}`}</span>
                      </div>
                      {out.length>0&&<div style={{fontSize:"9px",color:"#666",marginTop:"4px"}}>Eksik: {out.join(", ")}</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* B) Bağlam Efekt Badge'leri */}
          {result.context_effects&&(()=>{
            const ce=result.context_effects;
            const badges=[];
            if(ce.weather!=="normal") badges.push({icon:{normal:"",rain:"🌧️",heavy_rain:"⛈️",wind:"💨",snow:"❄️"}[ce.weather]||"🌤️", label:ce.weather_effect});
            if(ce.importance!=="normal") badges.push({icon:{must_win:"🔥",cup_final:"🏆",relegation:"📉",derby:"⚔️"}[ce.importance]||"", label:ce.importance_effect});
            if(ce.neutral_venue) badges.push({icon:"🌍",label:"Tarafsız Saha"});
            if(ce.home_rest_days<3) badges.push({icon:"😴",label:`Ev yorgun (${ce.home_rest_days}g)`});
            if(ce.away_rest_days<3) badges.push({icon:"😴",label:`Dep yorgun (${ce.away_rest_days}g)`});
            if(ce.home_rest_days>7) badges.push({icon:"⚡",label:`Ev dinç (${ce.home_rest_days}g)`});
            if(ce.away_rest_days>7) badges.push({icon:"⚡",label:`Dep dinç (${ce.away_rest_days}g)`});
            if(!badges.length) return null;
            return(
              <div style={{display:"flex",gap:"6px",flexWrap:"wrap",marginBottom:"10px"}}>
                {badges.map((b,i)=>(
                  <div key={i} style={{display:"flex",alignItems:"center",gap:"4px",padding:"4px 10px",borderRadius:"20px",fontSize:"10px",fontWeight:600,background:"rgba(206,147,216,0.1)",border:"1px solid rgba(206,147,216,0.2)",color:"#ce93d8"}}>
                    {b.icon} {b.label}
                  </div>
                ))}
              </div>
            );
          })()}

          {/* C) Model vs Tahmin BarChart */}
          {result.estimate_comparison&&(
            <div style={cardStyle}>
              <div style={{fontSize:"11px",color:"#ffd600",letterSpacing:"2px",fontWeight:700,marginBottom:"4px"}}>🎯 MODEL vs TAHMİNİN</div>
              {(()=>{
                const ec=result.estimate_comparison;
                const chartData=[
                  {name:"Ev",model:+(ec.model_home*100).toFixed(1),user:+(ec.user_home*100).toFixed(1)},
                  {name:"Ber",model:+(ec.model_draw*100).toFixed(1),user:+(ec.user_draw*100).toFixed(1)},
                  {name:"Dep",model:+(ec.model_away*100).toFixed(1),user:+(ec.user_away*100).toFixed(1)},
                ];
                const agBg={high:"rgba(0,200,83,0.12)",medium:"rgba(255,214,0,0.10)",low:"rgba(255,82,82,0.10)"};
                const agC={high:"#00e676",medium:"#ffd600",low:"#ff5252"};
                const agLabel={high:"🟢 Model ile uyumlusun",medium:"🟡 Orta düzeyde uyum",low:"🔴 Model ile anlaşmazlık var"};
                return(
                  <>
                    <ResponsiveContainer width="100%" height={160}>
                      <BarChart data={chartData} margin={{top:4,right:8,left:0,bottom:0}}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)"/>
                        <XAxis dataKey="name" stroke="#333" tick={{fill:"#888",fontSize:10}}/>
                        <YAxis stroke="#333" tick={{fill:"#555",fontSize:9}} tickFormatter={v=>`${v}%`} width={36}/>
                        <Tooltip contentStyle={{background:"#111",border:"1px solid rgba(255,255,255,0.1)",borderRadius:"8px",fontSize:"11px"}} formatter={(v,n)=>[`${v}%`,n]}/>
                        <Bar dataKey="model" name="Model" fill="#42a5f5" radius={[3,3,0,0]} maxBarSize={28}/>
                        <Bar dataKey="user"  name="Tahminin" fill="#ff9800" radius={[3,3,0,0]} maxBarSize={28}/>
                      </BarChart>
                    </ResponsiveContainer>
                    <div style={{marginTop:"8px",display:"inline-flex",padding:"4px 12px",borderRadius:"12px",fontSize:"10px",fontWeight:700,background:agBg[ec.agreement_level],color:agC[ec.agreement_level]}}>
                      {agLabel[ec.agreement_level]}
                    </div>
                  </>
                );
              })()}
            </div>
          )}
          {result.estimate_error&&(
            <div style={{padding:"8px 12px",background:"rgba(255,82,82,0.08)",border:"1px solid rgba(255,82,82,0.2)",borderRadius:"8px",color:"#ff5252",fontSize:"10px",marginBottom:"10px"}}>⚠️ {result.estimate_error}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── MAIN APP ──────────────────────────────────────────────────────────────

export default function App(){
  const[league,setLeague]=useState("PL");
  const[data,setData]=useState(null);
  const[selected,setSelected]=useState(null);
  const[loading,setLoading]=useState(true);
  const[connected,setConnected]=useState(false);
  const[activeTab,setActiveTab]=useState("analysis");
  const[btData,setBtData]=useState(null);
  const[btLoading,setBtLoading]=useState(false);
  const[clvData,setClvData]=useState(null);
  const[clvLoading,setClvLoading]=useState(false);

  const load=useCallback(async(lg)=>{
    setLoading(true);setSelected(null);
    try{
      const r=await fetch(`${API_BASE}/analyze/${lg}?bankroll=1000&days=14`);
      if(!r.ok) throw new Error(r.status);
      const d=await r.json();setData(d);setConnected(true);
    }catch(e){console.warn(e.message);setConnected(false);setData(null);}
    setLoading(false);
  },[]);

  const loadBacktest=useCallback(async(lg,mc=false,sens=false)=>{
    setBtLoading(true);setBtData(null);
    try{
      const params=[];if(mc)params.push("monte_carlo=true");if(sens)params.push("sensitivity=true");
      const r=await fetch(`${API_BASE}/backtest/${lg}${params.length?"?"+params.join("&"):""}`);
      if(!r.ok) throw new Error(r.status);
      setBtData(await r.json());
    }catch(e){console.warn(e.message);}
    setBtLoading(false);
  },[]);

  const loadCLV=useCallback(async()=>{
    setClvLoading(true);
    try{
      const r=await fetch(`${API_BASE}/clv-report`);
      if(!r.ok) throw new Error(r.status);
      setClvData(await r.json());
    }catch(e){setClvData(null);}
    setClvLoading(false);
  },[]);

  useEffect(()=>{load(league);},[league]);
  useEffect(()=>{
    if(activeTab==="dashboard"&&!clvData&&!clvLoading) loadCLV();
  },[activeTab]);

  const analyses=data?.analyses||[];
  const topVB=data?.top_value_bets||[];

  const TAB_BTN=(k,label)=>(
    <button key={k} onClick={()=>setActiveTab(k)} style={{
      padding:"8px 20px",borderRadius:"8px",border:"none",cursor:"pointer",
      fontSize:"12px",fontWeight:700,letterSpacing:"0.5px",transition:"0.2s",
      background:activeTab===k?"rgba(0,200,83,0.18)":"rgba(255,255,255,0.04)",
      color:activeTab===k?"#00e676":"#666",
      borderBottom:activeTab===k?"2px solid #00e676":"2px solid transparent",
    }}>{label}</button>
  );

  return(
    <div style={{fontFamily:"'DM Sans',sans-serif",background:"#0a0a0a",color:"#e0e0e0",minHeight:"100vh",padding:"16px",maxWidth:"1100px",margin:"0 auto"}}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@400;700;800&display=swap" rel="stylesheet"/>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>

      {/* ─── Header ─── */}
      <div style={{textAlign:"center",marginBottom:"16px"}}>
        <h1 style={{margin:"0 0 4px 0",fontSize:"22px",fontWeight:800,background:"linear-gradient(135deg,#00e676,#42a5f5)",WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent"}}>⚽ Value Bet Analyzer v8</h1>
        <p style={{margin:0,fontSize:"10px",color:"#666"}}>Dixon-Coles × Adaptif Kelly × Trust Gate × Risk Kontrolü</p>
      </div>

      {/* ─── Status bar ─── */}
      <div style={{borderRadius:"10px",padding:"9px 12px",marginBottom:"12px",fontSize:"11px",display:"flex",alignItems:"center",gap:"8px",flexWrap:"wrap",background:connected?"rgba(0,200,83,0.08)":"rgba(255,152,0,0.08)",border:`1px solid ${connected?"rgba(0,200,83,0.2)":"rgba(255,152,0,0.2)"}`}}>
        <div style={{width:"8px",height:"8px",borderRadius:"50%",background:connected?"#00e676":"#ff9800"}}/>
        <span style={{color:connected?"#00e676":"#ff9800",fontWeight:700}}>{connected?"v8 BAĞLI":"OFFLINE"}</span>
        <span style={{color:"#888"}}>|</span>
        <span style={{color:"#aaa"}}>{connected?`${ALL[league]?.name} | ${data?.hist_matches||0} maç | ${data?.upcoming||0} yaklaşan | ${data?.odds_source||""} | sezon ${data?.season||""}`:"Backend çalışmıyor"}</span>
      </div>

      {/* ─── Top value bets ─── */}
      {topVB.length>0&&(
        <div style={{background:"linear-gradient(135deg,rgba(0,200,83,0.08),rgba(66,165,245,0.04))",border:"1px solid rgba(0,200,83,0.15)",borderRadius:"12px",padding:"12px 14px",marginBottom:"16px"}}>
          <div style={{fontSize:"10px",color:"#00e676",letterSpacing:"2px",marginBottom:"8px",fontWeight:700}}>🎯 VALUE BETLER ({topVB.length})</div>
          <div style={{display:"flex",flexWrap:"wrap",gap:"5px"}}>
            {topVB.slice(0,10).map((b,i)=>(
              <div key={i} style={{background:"rgba(0,0,0,0.3)",borderRadius:"8px",padding:"5px 8px",fontSize:"10px",display:"flex",alignItems:"center",gap:"4px"}}>
                <span style={{color:"#aaa"}}>{b.match?.substring(0,22)}</span>
                <span style={{color:"#00e676",fontWeight:700,fontFamily:"'JetBrains Mono',monospace"}}>{b.market} @{b.odds}</span>
                <Badge value={b.value_pct/100}/>
                {b.confidence&&<span style={{fontSize:"8px",color:cc(b.confidence),fontFamily:"'JetBrains Mono',monospace"}}>{b.confidence}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─── League selector ─── */}
      <div style={{display:"flex",gap:"5px",marginBottom:"6px",flexWrap:"wrap",alignItems:"center"}}>
        <span style={{fontSize:"9px",color:"#555",letterSpacing:"2px",fontWeight:700,padding:"2px 6px"}}>LİGLER</span>
        {Object.entries(LEAGUES).map(([k,v])=>(
          <button key={k} onClick={()=>{setLeague(k);}} style={{padding:"6px 14px",borderRadius:"20px",border:league===k?"1px solid rgba(0,200,83,0.3)":"1px solid rgba(255,255,255,0.06)",background:league===k?"rgba(0,200,83,0.15)":"rgba(255,255,255,0.04)",color:league===k?"#00e676":"#777",fontSize:"11px",cursor:"pointer",fontWeight:600}}>{v.flag} {v.name}</button>
        ))}
      </div>
      <div style={{display:"flex",gap:"5px",marginBottom:"14px",flexWrap:"wrap",alignItems:"center"}}>
        <span style={{fontSize:"9px",color:"#555",letterSpacing:"2px",fontWeight:700,padding:"2px 6px"}}>KUPALAR</span>
        {Object.entries(CUPS).map(([k,v])=>(
          <button key={k} onClick={()=>{setLeague(k);}} style={{padding:"6px 14px",borderRadius:"20px",border:league===k?"1px solid rgba(0,200,83,0.3)":"1px solid rgba(255,255,255,0.06)",background:league===k?"rgba(0,200,83,0.15)":"rgba(255,255,255,0.04)",color:league===k?"#00e676":"#777",fontSize:"11px",cursor:"pointer",fontWeight:600}}>{v.flag} {v.name}</button>
        ))}
      </div>

      {/* ─── Stats grid ─── */}
      {data&&(
        <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:"6px",marginBottom:"12px"}}>
          {[
            {l:"Geçmiş",v:data.hist_matches,c:"#42a5f5"},
            {l:"Yaklaşan",v:data.upcoming,c:"#ccc"},
            {l:"Value",v:data.value_bets_count,c:data.value_bets_count>0?"#00e676":"#ff5252"},
            {l:"Oranlar",v:data.odds_source==="The Odds API"?"GERÇEK":"YOK",c:data.odds_source==="The Odds API"?"#00e676":"#ff5252"},
            {l:"Model",v:data.model_version||"v8",c:"#888"},
          ].map((s,i)=>(
            <div key={i} style={{background:"rgba(255,255,255,0.02)",borderRadius:"10px",padding:"8px",textAlign:"center",border:"1px solid rgba(255,255,255,0.04)"}}>
              <div style={{fontSize:"9px",color:"#777",marginBottom:"2px"}}>{s.l}</div>
              <div style={{fontSize:"14px",fontWeight:800,color:s.c,fontFamily:"'JetBrains Mono',monospace"}}>{s.v}</div>
            </div>
          ))}
        </div>
      )}

      {/* ─── Live lock ─── */}
      {data?.live_lock_reasons?.length>0&&(
        <div style={{background:"rgba(255,82,82,0.06)",border:"1px solid rgba(255,82,82,0.15)",borderRadius:"10px",padding:"10px 14px",marginBottom:"12px",fontSize:"11px",color:"#ff5252"}}>
          🔒 Canlı mod kilitli: {data.live_lock_reasons.join(", ")}
        </div>
      )}

      {/* ─── Tabs ─── */}
      <div style={{display:"flex",gap:"2px",marginBottom:"16px",borderBottom:"1px solid rgba(255,255,255,0.06)",paddingBottom:"0",flexWrap:"wrap"}}>
        {TAB_BTN("analysis","📋 Analysis")}
        {TAB_BTN("backtest","🧪 Backtest")}
        {TAB_BTN("dashboard","📊 Dashboard")}
        {TAB_BTN("manual","📝 Manuel")}
      </div>

      {/* ═══════════════════════════════════════════════════════════════════
          TAB: ANALYSIS
      ═══════════════════════════════════════════════════════════════════ */}
      {activeTab==="analysis"&&(
        <>
          {loading?(
            <Spinner/>
          ):(
            <>
              {analyses.map((a,i)=>{
                const mks=a.markets||[];
                const top5=mks.filter(m=>["home","draw","away","over25","under25"].includes(m.key));
                const bestV=mks.find(m=>m.is_value);
                const dt=a.date?new Date(a.date).toLocaleDateString("tr-TR",{day:"numeric",month:"short",weekday:"short"}):"";
                const isR=a.odds_source==="real";
                const conf=a.confidence||0;
                return(
                  <div key={i} onClick={()=>setSelected(selected===i?null:i)} style={{background:selected===i?"linear-gradient(135deg,rgba(0,200,83,0.08),rgba(0,230,118,0.04))":"rgba(255,255,255,0.02)",border:selected===i?"1px solid rgba(0,200,83,0.3)":"1px solid rgba(255,255,255,0.06)",borderRadius:"14px",padding:"14px",cursor:"pointer",transition:"0.3s",marginBottom:"8px"}}>
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:"8px"}}>
                      <span style={{fontSize:"10px",color:"#888"}}>{dt}{a.matchday?` • H${a.matchday}`:""}</span>
                      <div style={{display:"flex",gap:"4px",alignItems:"center"}}>
                        {a.steam_move&&<span style={{fontSize:"9px",padding:"2px 6px",borderRadius:"6px",fontWeight:700,background:"rgba(255,215,0,0.15)",color:"#ffd600"}}>🔥 STEAM</span>}
                        {a.neutral&&<span style={{fontSize:"9px",padding:"2px 6px",borderRadius:"6px",fontWeight:600,background:"rgba(66,165,245,0.12)",color:"#42a5f5"}}>NÖTR</span>}
                        <span style={{fontSize:"9px",padding:"2px 6px",borderRadius:"6px",fontWeight:600,background:isR?"rgba(0,200,83,0.12)":"rgba(255,152,0,0.12)",color:isR?"#00e676":"#ff9800"}}>{isR?"GERÇEK":"MODEL"}</span>
                        <span style={{fontSize:"10px",color:cc(conf),background:"rgba(255,255,255,0.04)",padding:"2px 6px",borderRadius:"6px",fontFamily:"'JetBrains Mono',monospace"}}>🎯{conf}</span>
                      </div>
                    </div>
                    <div style={{display:"flex",justifyContent:"center",alignItems:"center",gap:"10px",marginBottom:"8px"}}>
                      <div style={{textAlign:"right",flex:1}}>
                        <span style={{fontSize:"14px",fontWeight:700,color:"#e8e8e8"}}>{a.home_team}</span>
                        <div style={{fontSize:"9px",color:"#666"}}>E:{a.home_str?.home_atk||"?"}/{a.home_str?.home_def||"?"} D:{a.home_str?.away_atk||"?"}/{a.home_str?.away_def||"?"}</div>
                      </div>
                      <span style={{fontSize:"11px",color:"#444",padding:"2px 6px",border:"1px solid rgba(255,255,255,0.06)",borderRadius:"6px"}}>vs</span>
                      <div style={{textAlign:"left",flex:1}}>
                        <span style={{fontSize:"14px",fontWeight:700,color:"#e8e8e8"}}>{a.away_team}</span>
                        <div style={{fontSize:"9px",color:"#666"}}>E:{a.away_str?.home_atk||"?"}/{a.away_str?.home_def||"?"} D:{a.away_str?.away_atk||"?"}/{a.away_str?.away_def||"?"}</div>
                      </div>
                    </div>
                    <div style={{height:"4px",borderRadius:"2px",background:"rgba(255,255,255,0.06)",overflow:"hidden",marginBottom:"8px"}}><div style={{height:"100%",borderRadius:"2px",width:`${conf}%`,background:cc(conf),transition:"width 0.3s"}}/></div>
                    <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:"3px",marginBottom:"8px"}}>
                      {top5.map(m=>(
                        <div key={m.key} style={{textAlign:"center",padding:"5px 2px",borderRadius:"8px",background:m.is_value?"rgba(0,200,83,0.08)":"rgba(255,255,255,0.02)",border:m.is_value?"1px solid rgba(0,200,83,0.2)":"1px solid rgba(255,255,255,0.04)"}}>
                          <div style={{fontSize:"8px",color:"#777"}}>{m.label}</div>
                          <div style={{fontSize:"12px",fontWeight:700,fontFamily:"'JetBrains Mono',monospace",color:m.is_value?"#00e676":"#aaa"}}>{m.odds?.toFixed(2)}</div>
                          <div style={{fontSize:"8px",color:m.is_value?"#00c853":"#555"}}>{m.prob}%</div>
                          {m.best_odds_source&&<div style={{fontSize:"7px",color:"#555",overflow:"hidden",whiteSpace:"nowrap",textOverflow:"ellipsis"}}>{m.best_odds_source}</div>}
                        </div>
                      ))}
                    </div>
                    {bestV&&(
                      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",paddingTop:"6px",borderTop:"1px solid rgba(255,255,255,0.05)"}}>
                        <span style={{fontSize:"10px",color:"#999"}}>🎯 <strong style={{color:"#e0e0e0"}}>{bestV.label}</strong> @{bestV.odds?.toFixed(2)}{bestV.best_odds_source&&<span style={{color:"#666",marginLeft:"4px"}}>({bestV.best_odds_source})</span>}</span>
                        <div style={{display:"flex",gap:"3px",alignItems:"center"}}>
                          <Badge value={bestV.value_pct/100}/>
                          {(bestV.reason_flags||[]).slice(0,2).map((r,ri)=><span key={ri} style={{fontSize:"7px",color:"#888",background:"rgba(255,255,255,0.04)",padding:"1px 4px",borderRadius:"3px"}}>{r}</span>)}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

              {selected!==null&&analyses[selected]&&(()=>{
                const a=analyses[selected];
                const mks=a.markets||[];
                const mainMks=mks.filter(m=>!m.key.startsWith("cs_")&&!m.key.startsWith("iyms_")&&!m.key.startsWith("corner_"));
                const bks=a.bookmakers||[];
                const conf=a.confidence||0;
                const cc_comp=a.confidence_components||{};
                const marginComp=a.margin||[];
                const mv=a.odds_movement||{};
                return(
                  <div style={{background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.06)",borderRadius:"14px",padding:"18px",marginTop:"14px"}}>
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:"12px"}}>
                      <div>
                        <div style={{fontSize:"11px",color:"#00e676",letterSpacing:"2px",fontWeight:600}}>DETAYLI ANALİZ</div>
                        <h2 style={{fontSize:"17px",color:"#eee",marginTop:"2px"}}>{a.home_team} vs {a.away_team}</h2>
                      </div>
                      <div style={{display:"flex",gap:"8px",alignItems:"center"}}>
                        {a.steam_move&&<div style={{textAlign:"center"}}>
                          <div style={{fontSize:"16px"}}>🔥</div>
                          <div style={{fontSize:"8px",color:"#ffd600"}}>STEAM</div>
                          {a.steam_markets?.length>0&&<div style={{fontSize:"8px",color:"#888"}}>{a.steam_markets.join(",")}</div>}
                        </div>}
                        <div style={{textAlign:"center"}}>
                          <div style={{fontSize:"20px",fontWeight:800,color:cc(conf),fontFamily:"'JetBrains Mono',monospace"}}>{conf}</div>
                          <div style={{fontSize:"8px",color:"#888"}}>GÜVEN</div>
                        </div>
                      </div>
                    </div>

                    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"8px",marginBottom:"12px"}}>
                      {[{n:a.home_team,s:a.home_str,xg:a.home_xg,c:"#00e676"},{n:a.away_team,s:a.away_str,xg:a.away_xg,c:"#42a5f5"}].map((t,ti)=>(
                        <div key={ti} style={{background:"rgba(255,255,255,0.02)",borderRadius:"10px",padding:"10px",border:"1px solid rgba(255,255,255,0.05)"}}>
                          <div style={{fontSize:"12px",fontWeight:700,color:"#e0e0e0",marginBottom:"4px"}}>{t.n}</div>
                          <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:"3px"}}>
                            {[{l:"E.A",v:t.s?.home_atk,g:(t.s?.home_atk||1)>1},{l:"E.D",v:t.s?.home_def,g:(t.s?.home_def||1)<1},{l:"D.A",v:t.s?.away_atk,g:(t.s?.away_atk||1)>1},{l:"D.D",v:t.s?.away_def,g:(t.s?.away_def||1)<1},{l:"xG",v:t.xg}].map((x,xi)=>(
                              <div key={xi} style={{textAlign:"center"}}>
                                <div style={{fontSize:"7px",color:"#777"}}>{x.l}</div>
                                <div style={{fontSize:"11px",fontWeight:800,fontFamily:"'JetBrains Mono',monospace",color:x.g===true?"#00e676":x.g===false?"#ff5252":x.l==="xG"?t.c:"#ccc"}}>{x.v||"?"}</div>
                              </div>
                            ))}
                          </div>
                          <div style={{fontSize:"8px",color:"#666",marginTop:"3px"}}>{t.s?.n||0} maç (E:{t.s?.home_n||0} D:{t.s?.away_n||0})</div>
                        </div>
                      ))}
                    </div>

                    {/* Confidence components */}
                    {Object.keys(cc_comp).length>0&&(
                      <div style={{display:"flex",gap:"4px",flexWrap:"wrap",marginBottom:"10px"}}>
                        {Object.entries(cc_comp).map(([k,v])=>(
                          <span key={k} style={{fontSize:"8px",color:"#888",background:"rgba(255,255,255,0.04)",padding:"2px 6px",borderRadius:"4px"}}>{k}:{v}</span>
                        ))}
                        {a.steam_move&&<span style={{fontSize:"8px",color:"#ffd600",background:"rgba(255,215,0,0.08)",padding:"2px 6px",borderRadius:"4px"}}>steam:+3</span>}
                      </div>
                    )}

                    {/* Odds movement */}
                    {Object.keys(mv).length>0&&(
                      <div style={{marginBottom:"10px",padding:"8px 10px",background:"rgba(255,255,255,0.02)",borderRadius:"8px",border:"1px solid rgba(255,255,255,0.05)"}}>
                        <div style={{fontSize:"9px",color:"#888",letterSpacing:"1px",fontWeight:700,marginBottom:"5px"}}>📈 ORAN HAREKETİ</div>
                        <div style={{display:"flex",gap:"6px",flexWrap:"wrap"}}>
                          {Object.entries(mv).map(([mk,info])=>{
                            const dirC=info.direction==="up"?"#00e676":info.direction==="down"?"#ff5252":"#888";
                            const dirIcon=info.direction==="up"?"↑":info.direction==="down"?"↓":"→";
                            return(
                              <div key={mk} style={{fontSize:"10px",background:"rgba(255,255,255,0.03)",borderRadius:"6px",padding:"3px 7px",display:"flex",alignItems:"center",gap:"4px"}}>
                                <span style={{color:"#888"}}>{mk}</span>
                                <span style={{color:dirC,fontWeight:700}}>{dirIcon}</span>
                                <span style={{fontSize:"8px",color:"#555"}}>{info.bk_count}bk</span>
                                {info.steam&&<span style={{fontSize:"8px",color:"#ffd600",fontWeight:700}}>STEAM</span>}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Markets table */}
                    <div style={{fontSize:"10px",color:"#888",letterSpacing:"1px",marginBottom:"4px",fontWeight:600}}>📋 MARKETLER</div>
                    <table style={{width:"100%",borderCollapse:"separate",borderSpacing:"0 3px",fontSize:"11px"}}>
                      <thead><tr style={{color:"#666",fontSize:"9px",letterSpacing:"1px"}}>
                        <th style={{textAlign:"left",padding:"4px 6px"}}>MARKET</th>
                        <th style={{textAlign:"center",padding:"4px 6px"}}>MODEL</th>
                        <th style={{textAlign:"center",padding:"4px 6px"}}>ORAN</th>
                        <th style={{textAlign:"center",padding:"4px 6px"}}>KAYNAK</th>
                        <th style={{textAlign:"center",padding:"4px 6px"}}>ADİL</th>
                        <th style={{textAlign:"center",padding:"4px 6px"}}>TİP</th>
                        <th style={{textAlign:"center",padding:"4px 6px"}}>DEĞER</th>
                        <th style={{textAlign:"right",padding:"4px 6px"}}>BAHİS</th>
                      </tr></thead>
                      <tbody>
                        {mainMks.map(m=>{const mc2=m.market_class||"informational";return(
                          <tr key={m.key} style={{background:m.is_value?"rgba(0,200,83,0.06)":"rgba(255,255,255,0.01)"}}>
                            <td style={{color:m.is_value?"#e0e0e0":"#888",fontWeight:m.is_value?600:400,padding:"7px 6px"}}>{m.label}</td>
                            <td style={{textAlign:"center",padding:"7px 6px",fontFamily:"'JetBrains Mono',monospace",color:m.is_value?"#00e676":"#999",fontWeight:700}}>{m.prob}%</td>
                            <td style={{textAlign:"center",padding:"7px 6px",fontFamily:"'JetBrains Mono',monospace",color:"#ccc"}}>{m.odds?.toFixed(2)}</td>
                            <td style={{textAlign:"center",padding:"7px 4px",fontSize:"9px",color:"#666",maxWidth:"80px",overflow:"hidden",whiteSpace:"nowrap",textOverflow:"ellipsis"}}>
                              {m.best_odds_source||<span style={{color:"#444"}}>{m.odds_source==="real"?"G":"M"}</span>}
                            </td>
                            <td style={{textAlign:"center",padding:"7px 6px",fontFamily:"'JetBrains Mono',monospace",color:"#555",fontSize:"10px"}}>{m.model_fair_odds?.toFixed(2)||"-"}</td>
                            <td style={{textAlign:"center",padding:"7px 6px"}}><span style={{fontSize:"7px",padding:"2px 6px",borderRadius:"6px",fontWeight:600,background:MC_C[mc2]==="tg"?"rgba(0,200,83,0.12)":MC_C[mc2]==="tn"?"rgba(66,165,245,0.12)":"rgba(255,152,0,0.12)",color:MC_C[mc2]==="tg"?"#00e676":MC_C[mc2]==="tn"?"#42a5f5":"#ff9800"}}>{MC_L[mc2]||mc2}</span></td>
                            <td style={{textAlign:"center",padding:"7px 6px"}}>{m.is_value?<Badge value={m.value_pct/100}/>:m.value_eligible?<span style={{color:"#555",fontSize:"8px"}}>{"<%5"}</span>:<span style={{color:"#444",fontSize:"8px"}}>-</span>}</td>
                            <td style={{textAlign:"right",padding:"7px 6px",fontFamily:"'JetBrains Mono',monospace",color:m.is_value?"#00e676":"#555",fontWeight:700}}>{m.is_value?`${m.bet}₺`:"-"}</td>
                          </tr>
                        );})}
                      </tbody>
                    </table>

                    {/* All odds per market (best_odds_detail) */}
                    {a.best_odds_detail&&Object.keys(a.best_odds_detail).length>0&&(
                      <div style={{marginTop:"10px",padding:"10px",background:"rgba(66,165,245,0.04)",borderRadius:"8px",border:"1px solid rgba(66,165,245,0.1)"}}>
                        <div style={{fontSize:"9px",color:"#42a5f5",letterSpacing:"1px",fontWeight:700,marginBottom:"6px"}}>🏆 EN İYİ ORANLAR (bookmaker karşılaştırması)</div>
                        <div style={{display:"flex",gap:"6px",flexWrap:"wrap"}}>
                          {["home","draw","away","over25","under25"].map(mk=>{
                            const d=a.best_odds_detail[mk];
                            if(!d) return null;
                            return(
                              <div key={mk} style={{background:"rgba(255,255,255,0.03)",borderRadius:"6px",padding:"5px 8px",minWidth:"80px"}}>
                                <div style={{fontSize:"8px",color:"#666",marginBottom:"2px"}}>{mk}</div>
                                <div style={{fontSize:"13px",fontWeight:800,color:"#e0e0e0",fontFamily:"'JetBrains Mono',monospace"}}>{d.best_odds?.toFixed(2)}</div>
                                <div style={{fontSize:"8px",color:"#42a5f5"}}>{d.bookmaker}</div>
                                {d.all_odds?.length>1&&(
                                  <div style={{fontSize:"7px",color:"#555",marginTop:"2px"}}>
                                    {d.all_odds.slice(0,3).map((o,i)=><span key={i} style={{marginRight:"4px"}}>{o.bk?.substring(0,6)}:{o.odds?.toFixed(2)}</span>)}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Margin comparison */}
                    {marginComp.length>0&&(
                      <div style={{marginTop:"10px",padding:"8px 10px",background:"rgba(255,255,255,0.02)",borderRadius:"8px",border:"1px solid rgba(255,255,255,0.05)"}}>
                        <div style={{fontSize:"9px",color:"#888",letterSpacing:"1px",fontWeight:700,marginBottom:"5px"}}>📊 MARGIN KARŞILAŞTIRMA</div>
                        <div style={{display:"flex",gap:"6px",flexWrap:"wrap"}}>
                          {marginComp.map((bk,bi)=>(
                            <div key={bi} style={{fontSize:"9px",display:"flex",alignItems:"center",gap:"4px",background:bk.lowest_margin?"rgba(0,200,83,0.08)":"rgba(255,255,255,0.02)",borderRadius:"6px",padding:"3px 7px",border:bk.lowest_margin?"1px solid rgba(0,200,83,0.2)":"none"}}>
                              {bk.lowest_margin&&<span style={{color:"#00e676",fontSize:"8px"}}>★</span>}
                              <span style={{color:"#aaa"}}>{bk.bookmaker}</span>
                              <span style={{fontFamily:"'JetBrains Mono',monospace",color:bk.margin<0.04?"#00e676":bk.margin<0.07?"#ffd600":"#ff5252",fontWeight:700}}>%{bk.margin_pct}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Bookmakers raw table */}
                    {bks.length>0&&(
                      <div style={{marginTop:"10px",background:"rgba(255,255,255,0.02)",borderRadius:"10px",padding:"12px",border:"1px solid rgba(255,255,255,0.06)"}}>
                        <div style={{fontSize:"10px",color:"#42a5f5",letterSpacing:"2px",marginBottom:"8px",fontWeight:700}}>📊 BAHİS SİTELERİ ({bks.length})</div>
                        <table style={{width:"100%",borderCollapse:"separate",borderSpacing:"0 3px",fontSize:"11px"}}>
                          <thead><tr style={{color:"#666",fontSize:"8px"}}><th style={{textAlign:"left"}}>SİTE</th><th>1</th><th>X</th><th>2</th><th>Ü2.5</th><th>A2.5</th><th>MRJ</th></tr></thead>
                          <tbody>{bks.map((bk,bi)=>{
                            const o=bk.markets||{};
                            const mg=bk.margin!=null?(bk.margin*100).toFixed(1):o.home&&o.draw&&o.away?((1/o.home+1/o.draw+1/o.away-1)*100).toFixed(1):"?";
                            return(
                              <tr key={bi}><td><span style={{color:"#ccc",fontWeight:600,fontSize:"11px"}}>{bk.name}</span></td>
                              <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#ccc"}}>{o.home?.toFixed(2)||"-"}</td>
                              <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#ccc"}}>{o.draw?.toFixed(2)||"-"}</td>
                              <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#ccc"}}>{o.away?.toFixed(2)||"-"}</td>
                              <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#ccc"}}>{o.over25?.toFixed(2)||"-"}</td>
                              <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",color:"#ccc"}}>{o.under25?.toFixed(2)||"-"}</td>
                              <td style={{textAlign:"center",fontFamily:"'JetBrains Mono',monospace",fontWeight:600,color:parseFloat(mg)<5?"#00e676":parseFloat(mg)<8?"#ffd600":"#ff5252"}}>%{mg}</td></tr>
                            );
                          })}</tbody>
                        </table>
                      </div>
                    )}

                    <div style={{marginTop:"10px",padding:"8px",background:"rgba(255,215,0,0.04)",borderRadius:"8px",border:"1px solid rgba(255,215,0,0.1)"}}>
                      <div style={{fontSize:"9px",color:"#999",lineHeight:1.5}}>
                        <strong style={{color:"#ffd600"}}>v8:</strong> Dixon-Coles | Adaptif Kelly (cap %2.5) | Min edge %5 | Max 1/maç | Günlük %8 | Trust gate{a.neutral&&" | 🌍 Nötr saha"}
                        <br/><span style={{color:"#555"}}>⚠️ Analiz aracıdır, bahis önerisi değildir.</span>
                      </div>
                    </div>
                  </div>
                );
              })()}

              {analyses.length===0&&connected&&(
                <div style={{textAlign:"center",padding:"30px",color:"#666",fontSize:"12px"}}>Maç bulunamadı.</div>
              )}
            </>
          )}
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          TAB: BACKTEST
      ═══════════════════════════════════════════════════════════════════ */}
      {activeTab==="backtest"&&(
        <div>
          <div style={{display:"flex",gap:"8px",marginBottom:"14px",flexWrap:"wrap",alignItems:"center"}}>
            <button onClick={()=>loadBacktest(league)} disabled={btLoading} style={{padding:"8px 16px",borderRadius:"8px",border:"1px solid rgba(0,200,83,0.3)",background:"rgba(0,200,83,0.10)",color:"#00e676",fontSize:"11px",fontWeight:700,cursor:"pointer"}}>
              {btLoading?"⏳ Çalışıyor...":"🧪 Backtest Çalıştır"}
            </button>
            <button onClick={()=>loadBacktest(league,true,true)} disabled={btLoading} style={{padding:"8px 16px",borderRadius:"8px",border:"1px solid rgba(66,165,245,0.3)",background:"rgba(66,165,245,0.08)",color:"#42a5f5",fontSize:"11px",fontWeight:700,cursor:"pointer"}}>
              🎲 Monte Carlo + Hassasiyet
            </button>
            {btData&&<span style={{fontSize:"10px",color:"#555"}}>Son: {ALL[league]?.name}</span>}
          </div>
          {btLoading&&<Spinner/>}
          {btData&&!btLoading&&(
            <Panel title="📊 BACKTEST SONUÇLARI" accent="#00e676">
              <BacktestSummary bt={btData}/>
            </Panel>
          )}
          {!btData&&!btLoading&&(
            <NoData msg="Backtest çalıştır — lig bazlı ROI, kalibrasyon ve güven durumu gösterilir."/>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          TAB: DASHBOARD
      ═══════════════════════════════════════════════════════════════════ */}
      {activeTab==="dashboard"&&(
        <div>
          {/* Load controls */}
          <div style={{display:"flex",gap:"8px",marginBottom:"14px",flexWrap:"wrap",alignItems:"center"}}>
            {!btData&&(
              <button onClick={()=>loadBacktest(league,true)} disabled={btLoading} style={{padding:"8px 16px",borderRadius:"8px",border:"1px solid rgba(255,215,0,0.25)",background:"rgba(255,215,0,0.06)",color:"#ffd600",fontSize:"11px",fontWeight:700,cursor:"pointer"}}>
                {btLoading?"⏳ Yükleniyor...":"📈 Backtest Yükle (Monte Carlo)"}
              </button>
            )}
            <button onClick={loadCLV} disabled={clvLoading} style={{padding:"8px 16px",borderRadius:"8px",border:"1px solid rgba(66,165,245,0.25)",background:"rgba(66,165,245,0.06)",color:"#42a5f5",fontSize:"11px",fontWeight:700,cursor:"pointer"}}>
              {clvLoading?"⏳ Yükleniyor...":"🔄 CLV Yenile"}
            </button>
            {btData&&<span style={{fontSize:"10px",color:"#555"}}>Backtest: {ALL[league]?.name} ✓</span>}
          </div>

          {/* Row 1: BankrollChart + CalibrationDiagram */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"12px",marginBottom:"12px"}}>
            <Panel title="📈 BANKROLL SİMÜLASYONU" accent="#00e676"
              extra={btData?.monte_carlo&&<span style={{fontSize:"8px",color:"#555"}}>{btData.monte_carlo.n_sim} sim</span>}>
              {btLoading?<Spinner/>:<BankrollChart bt={btData}/>}
            </Panel>
            <Panel title="🎯 KALİBRASYON DİYAGRAMI" accent="#ffd600">
              {btLoading?<Spinner/>:<CalibrationDiagram bt={btData}/>}
            </Panel>
          </div>

          {/* Row 2: MarketHeatmap full width */}
          <Panel title="🟩 MARKET PERFORMANS ISISI" accent="#ff9800">
            {btLoading?<Spinner/>:<MarketHeatmap bt={btData}/>}
          </Panel>

          {/* Row 3: EloTable */}
          <Panel title="🏆 ELO RATING TABLOSU" accent="#42a5f5"
            extra={<span style={{fontSize:"9px",color:"#555"}}>{ALL[league]?.name} — {analyses.length} maç</span>}>
            <EloTable analyses={analyses}/>
          </Panel>

          {/* Row 4: CLV Trend */}
          <Panel title="📉 CLV TREND (Kapanış Oran Değeri)" accent="#ce93d8"
            extra={clvData?.total_entries!=null&&<span style={{fontSize:"9px",color:"#555"}}>{clvData.total_entries} kayıt</span>}>
            {clvLoading?<Spinner/>:<CLVTrend clv={clvData}/>}
          </Panel>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          TAB: MANUEL ANALİZ
      ═══════════════════════════════════════════════════════════════════ */}
      {activeTab==="manual"&&<ManualTab/>}

      {/* ─── Footer ─── */}
      <div style={{marginTop:"24px",padding:"12px",textAlign:"center",borderTop:"1px solid rgba(255,255,255,0.04)"}}>
        <p style={{fontSize:"9px",color:"#555",lineHeight:1.5}}>⚠️ Eğitim amaçlıdır. Bahis finansal risk içerir.</p>
      </div>
    </div>
  );
}
