"""Tahmin doğrulama"""
import logging

logger = logging.getLogger(__name__)

def validate_prediction_context(hxg:float,axg:float,confidence:int,edge:float,market_key:str,odds:float)->dict:
    flags=[]
    reject=False

    if hxg>3.5:flags.append("anomaly_hxg_extreme");reject=True
    if axg>3.5:flags.append("anomaly_axg_extreme");reject=True
    if hxg<0.15 and axg<0.15:flags.append("anomaly_both_xg_near_zero");reject=True
    if abs(hxg-axg)>2.5:flags.append("anomaly_xg_gap_extreme")

    if edge>0.40:
        flags.append("anomaly_edge_too_high")
        reject=True
    if edge>0.20:
        flags.append("caution_high_edge")
    if edge>0.12 and confidence<55:
        flags.append("anomaly_high_edge_low_conf")
        reject=True

    if odds>1:
        implied=1/odds
        model_prob=edge/odds+implied if odds>1 else 0
        gap=abs(model_prob-implied)
        if gap>0.35:
            flags.append("anomaly_prob_gap_extreme")
            reject=True
        elif gap>0.20:
            flags.append("caution_prob_gap_high")

    if reject:
        logger.warning(
            "sanity_reject market=%s hxg=%.2f axg=%.2f edge=%.3f conf=%d flags=%s",
            market_key, hxg, axg, edge, confidence, flags,
        )
    elif flags:
        logger.debug(
            "sanity_caution market=%s flags=%s",
            market_key, flags,
        )

    return{"reject":reject,"flags":flags}
