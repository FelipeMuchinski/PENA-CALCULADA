"""
calculation.py
Lógica de dosimetria penal — método trifásico (CP Brasileiro).

Alterações v1.1:
  - Arma de fogo uso permitido: aumento fixo de +2/3
  - Arma de fogo uso restrito/proibido: aumento em dobro (2x)
  - Atenuante inominada (Art. 66) movida para a fase 2 (mitigating)
  - Arrependimento Posterior (Art. 16) adicionado à fase 3 (decrease)
  - Tráfico Privilegiado (Art. 33 §4º Lei 11.343) adicionado à fase 3 (decrease)
"""

from dataclasses import dataclass, field
from typing import List

# Frações padrão para causas de aumento/diminuição
FRACTION_VALUES: dict[str, float] = {
    "none":  0.0,
    "1/8":   1 / 8,
    "1/6":   1 / 6,
    "1/5":   1 / 5,
    "1/4":   1 / 4,
    "1/3":   1 / 3,
    "1/2":   1 / 2,
    "2/3":   2 / 3,
    "3/4":   3 / 4,
}

# Valores especiais de aumento (não são frações somadas — são multiplicadores diretos)
# "fixed_2/3"  → aumenta fixo de 2/3  → multiplica por 1 + 2/3 = 5/3
# "double"     → dobro da pena        → multiplica por 2
SPECIAL_INCREASE: dict[str, float] = {
    "fixed_2/3": 5 / 3,   # arma de fogo uso permitido: pena × 5/3
    "double":    2.0,      # arma de fogo uso restrito: pena × 2
}


@dataclass
class CalculationState:
    """Estado completo do formulário de cálculo."""
    min_years:  int = 0
    min_months: int = 0
    max_years:  int = 0
    max_months: int = 0
    # Fase 1 — 8 circunstâncias judiciais (Art. 59)
    judicial_circumstances: List[bool] = field(default_factory=lambda: [False] * 8)
    # Fase 2 — 9 agravantes (Art. 61) e 9 atenuantes (Arts. 65 + 66 inominada)
    aggravating: List[bool] = field(default_factory=lambda: [False] * 9)
    mitigating:  List[bool] = field(default_factory=lambda: [False] * 9)
    # Fase 3 — até 6 causas de aumento e 6 causas de diminuição
    increase_factors: List[str] = field(default_factory=lambda: ["none"] * 6)
    decrease_factors: List[str] = field(default_factory=lambda: ["none"] * 6)


@dataclass
class PhaseResult:
    """Resultado de uma fase do cálculo."""
    days:           int = 0
    years:          int = 0
    months:         int = 0
    remaining_days: int = 0


@dataclass
class FullCalculationResult:
    """Resultado completo das três fases."""
    phase1:   PhaseResult = field(default_factory=PhaseResult)
    phase2:   PhaseResult = field(default_factory=PhaseResult)
    phase3:   PhaseResult = field(default_factory=PhaseResult)
    is_valid: bool = False


def days_to_result(total_days: float) -> PhaseResult:
    """Converte total de dias em anos, meses e dias restantes."""
    safe_total     = max(0, round(total_days))
    years          = safe_total // 365
    remaining      = safe_total % 365
    months         = remaining  // 30
    remaining_days = remaining  % 30
    return PhaseResult(days=safe_total, years=years,
                       months=months, remaining_days=remaining_days)


def apply_increase(days: float, factor: str) -> float:
    """
    Aplica uma causa de aumento sobre os dias.
    Suporta frações normais (FRACTION_VALUES) e valores especiais (SPECIAL_INCREASE).
    """
    if not factor or factor == "none":
        return days
    if factor in SPECIAL_INCREASE:
        return days * SPECIAL_INCREASE[factor]
    if factor in FRACTION_VALUES:
        return days * (1 + FRACTION_VALUES[factor])
    return days


def apply_decrease(days: float, factor: str) -> float:
    """
    Aplica uma causa de diminuição sobre os dias.
    Para causas com intervalo (ex: 1/3 a 2/3), usa o valor selecionado.
    """
    if not factor or factor == "none":
        return days
    if factor in FRACTION_VALUES:
        return days * (1 - FRACTION_VALUES[factor])
    return days


def calculate(state: CalculationState) -> FullCalculationResult:
    """
    Executa o cálculo trifásico da pena.

    Fase 1 — Art. 59: circunstâncias judiciais deslocam a pena-base
    Fase 2 — Arts. 61/65/66: agravantes e atenuantes (±1/6 cada)
    Fase 3 — causas de aumento e diminuição por frações legais
    """
    min_days = state.min_years * 365 + state.min_months * 30
    max_days = state.max_years * 365 + state.max_months * 30

    # Valida os limites mínimo e máximo
    if min_days <= 0 or max_days <= 0 or min_days > max_days:
        return FullCalculationResult(
            phase1=days_to_result(0),
            phase2=days_to_result(0),
            phase3=days_to_result(0),
            is_valid=False,
        )

    # ── Fase 1: Pena-base (Art. 59) ──────────────────────────────────────────
    # Cada circunstância judicial negativa desloca proporcionalmente entre min e max
    negative_count = sum(1 for c in state.judicial_circumstances if c)
    phase1_days = min_days + (negative_count / 8) * (max_days - min_days)

    # ── Fase 2: Agravantes e Atenuantes ──────────────────────────────────────
    # Cada circunstância agrava ou atenua 1/6 da pena-base (Arts. 61, 65, 66)
    agg_count = sum(1 for a in state.aggravating if a)
    mit_count = sum(1 for m in state.mitigating  if m)
    net = agg_count - mit_count
    phase2_days = phase1_days + net * (1 / 6) * phase1_days
    # Limites: não pode ficar abaixo do mínimo nem acima de máximo × 1.5
    phase2_days = max(min_days, min(max_days * 1.5, phase2_days))

    # ── Fase 3: Causas de aumento ────────────────────────────────────────────
    phase3_days = phase2_days
    for factor in state.increase_factors:
        phase3_days = apply_increase(phase3_days, factor)

    # ── Fase 3: Causas de diminuição ─────────────────────────────────────────
    for factor in state.decrease_factors:
        phase3_days = apply_decrease(phase3_days, factor)

    phase3_days = max(0, phase3_days)

    return FullCalculationResult(
        phase1=days_to_result(phase1_days),
        phase2=days_to_result(phase2_days),
        phase3=days_to_result(phase3_days),
        is_valid=True,
    )


def format_duration(result: PhaseResult) -> str:
    """Formata um PhaseResult como texto legível em português."""
    parts = []
    if result.years > 0:
        parts.append(f"{result.years} ano{'s' if result.years != 1 else ''}")
    if result.months > 0:
        parts.append(f"{result.months} {'meses' if result.months != 1 else 'mês'}")
    if result.remaining_days > 0 or not parts:
        parts.append(f"{result.remaining_days} dia{'s' if result.remaining_days != 1 else ''}")
    return ", ".join(parts)


def suggest_regime(phase3: PhaseResult) -> str:
    """Sugere o regime inicial de cumprimento com base na pena definitiva."""
    if phase3.years >= 8:
        return "Regime Fechado — pena superior a 8 anos (art. 33, §2, a, CP)"
    elif phase3.years >= 4:
        return "Regime Semiaberto — pena superior a 4 anos (art. 33, §2, b, CP)"
    else:
        return "Regime Aberto — pena até 4 anos (art. 33, §2, c, CP)"
