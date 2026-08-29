from __future__ import annotations

from app.research.ncaaf.contracts import FEATURE_SET_VERSION, FeatureDefinition

METRICS = (
    "off_ppa",
    "def_ppa_allowed",
    "pass_ppa",
    "rush_ppa",
    "success_rate",
    "explosive_rate",
    "yards_per_play",
    "yards_per_drive",
    "points_per_drive",
    "plays_per_game",
    "drives_per_game",
    "havoc_rate",
)

DESCRIPTIONS = {
    "off_ppa": "Mean CFBD PPA on eligible offensive scrimmage plays.",
    "def_ppa_allowed": "Mean opponent CFBD PPA allowed on eligible defensive scrimmage plays; lower is better.",
    "pass_ppa": "Mean CFBD PPA on pass attempts, sacks, and interceptions.",
    "rush_ppa": "Mean CFBD PPA on designed/provider-classified rushing plays.",
    "success_rate": "Share of scrimmage plays gaining 50% of needed yards on first down, 70% on second, and 100% later.",
    "explosive_rate": "Share of pass plays gaining at least 20 yards or rushes gaining at least 10 yards.",
    "yards_per_play": "Scrimmage yards divided by eligible scrimmage plays.",
    "yards_per_drive": "Provider drive yards divided by drives.",
    "points_per_drive": "Change in offense score during provider drives divided by drives.",
    "plays_per_game": "Eligible scrimmage plays in the prior game; robust pace proxy.",
    "drives_per_game": "Provider drives in the prior game; robust pace proxy.",
    "havoc_rate": "Defensive sacks, interceptions, and opponent-fumble recoveries divided by scrimmage plays faced.",
}


def feature_definitions() -> tuple[FeatureDefinition, ...]:
    definitions: list[FeatureDefinition] = []
    for name, description, formula, source in (
        ("neutral_site", "Provider neutral-site indicator.", "boolean provider game fact", "games"),
        ("conference_game", "Provider conference-game indicator.", "boolean provider game fact", "games"),
        ("postseason", "Non-regular-season indicator.", "season_type != regular", "games"),
        ("covid_2020_regime", "Explicit 2020 schedule/regime indicator.", "season == 2020", "games"),
        (
            "home_conference",
            "Effective-season home conference label.",
            "provider/effective-season conference",
            "program membership",
        ),
        (
            "away_conference",
            "Effective-season away conference label.",
            "provider/effective-season conference",
            "program membership",
        ),
        ("home_classification", "Effective-season home classification.", "provider game classification", "games"),
        ("away_classification", "Effective-season away classification.", "provider game classification", "games"),
        (
            "venue_id",
            "Provider venue identity; current venue attributes are not treated as historical facts.",
            "provider venue ID",
            "games",
        ),
    ):
        definitions.append(
            FeatureDefinition(
                name=name,
                description=description,
                formula=formula,
                required_sources=(source,),
                direction="context",
                minimum_sample=0,
                missingness="null when the source does not provide it",
                point_in_time_rule="scheduled-game context known by the declared prediction cutoff",
            )
        )
    for side in ("home", "away"):
        definitions.append(
            FeatureDefinition(
                name=f"{side}_rest_days",
                description=f"Calendar rest for the {side} program since its latest available prior game.",
                formula="(target kickoff - latest prior-game kickoff) / 86400",
                required_sources=("games",),
                direction="more means more rest",
                minimum_sample=1,
                missingness="null without a prior resolved game",
                point_in_time_rule="latest prior game must satisfy available_at <= prediction_as_of",
            )
        )
        for suffix, description in (
            ("prior_games_available", "resolved prior games available"),
            ("current_season_games", "current-season games available"),
            ("pbp_games_available", "prior games with PBP"),
            ("drive_games_available", "prior games with drives"),
            ("team_stat_games_available", "prior games with team statistics"),
            ("pbp_coverage_ratio", "fraction of prior games with PBP"),
            ("drive_coverage_ratio", "fraction of prior games with drives"),
            ("team_stat_coverage_ratio", "fraction of prior games with team statistics"),
            ("wallclock_coverage", "fraction of offensive plays with wall-clock timestamps"),
            ("reconstructed_source", "whether reconstructed source facts contribute"),
            ("opponent_adjustment_available", "whether schedule adjustment has opponent support"),
            ("current_weight", "n/(n+3) current-season blending weight"),
            ("prior_weight", "3/(n+3) prior blending weight"),
        ):
            definitions.append(
                FeatureDefinition(
                    name=f"{side}_{suffix}",
                    description=f"{side.title()} {description}.",
                    formula=description,
                    required_sources=("games", "plays", "drives", "team game statistics"),
                    direction="quality/data-depth",
                    minimum_sample=0,
                    missingness="zero/count/false are distinct from null; ratios are null with no denominator",
                    point_in_time_rule="counts only facts available at prediction_as_of and excludes the target game",
                )
            )
        for metric in METRICS:
            for suffix, formula, sample in (
                ("last3", "arithmetic mean of the latest up to 3 available prior games", 1),
                ("last5", "arithmetic mean of the latest up to 5 available prior games", 1),
                ("season", "arithmetic mean of available prior games in the target season", 1),
                ("prior", "prior three-season program mean, falling back to the available population mean", 1),
                ("blended", "n/(n+3) current-season mean + 3/(n+3) prior mean", 0),
            ):
                definitions.append(
                    FeatureDefinition(
                        name=f"{side}_{metric}_{suffix}",
                        description=f"{side.title()} {DESCRIPTIONS[metric]}",
                        formula=formula,
                        required_sources=("games", "plays", "drives"),
                        direction="metric-specific",
                        minimum_sample=sample,
                        missingness="null when neither current history nor a population/prior estimate exists",
                        point_in_time_rule="uses only games with reconstructed available_at <= prediction_as_of; excludes target game",
                    )
                )
        for metric in ("off_ppa", "def_ppa_allowed", "success_rate", "yards_per_play"):
            definitions.append(
                FeatureDefinition(
                    name=f"{side}_{metric}_opponent_adjusted",
                    description=f"Prior-only schedule-adjusted {metric} for {side}.",
                    formula="last-5 raw mean - mean prior-only opponent opposite-unit strength + prior-only population mean",
                    required_sources=("games", "plays"),
                    direction="metric-specific",
                    minimum_sample=1,
                    missingness="null when opponent identity or opponent history is insufficient",
                    point_in_time_rule="opponent strength uses only opponent games available before the target as-of",
                )
            )
    for metric in METRICS:
        definitions.append(
            FeatureDefinition(
                name=f"home_minus_away_{metric}",
                description=f"Home minus away blended {metric}.",
                formula=f"home_{metric}_blended - away_{metric}_blended",
                required_sources=("derived team histories",),
                direction="positive favors the home side for offense metrics; metric-specific otherwise",
                minimum_sample=0,
                missingness="null if either side is unavailable",
                point_in_time_rule="inherits both component as-of rules",
            )
        )
    return tuple(sorted(definitions, key=lambda item: item.name))


def feature_definition(name: str) -> FeatureDefinition:
    try:
        return next(item for item in feature_definitions() if item.name == name)
    except StopIteration:
        raise KeyError(f"feature is not registered in {FEATURE_SET_VERSION}: {name}") from None
