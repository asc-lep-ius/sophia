/**
 * Geometry for the dashboard's figures.
 *
 * Pure functions over numbers the server already computed: a figure is a
 * second rendering of a table the page also ships, never a place a value first
 * appears. See `docs/frontend-dashboard-charts.md` for why nothing here is a
 * chart library.
 */

export type FigureDatum = {
  key: string;
  label: string;
  value: number;
  /** What the table cell and the spoken summary say; never re-derived. */
  display: string;
};

export type FigureBar = FigureDatum & {
  /** Share of the figure's width, 0 to 100. */
  percent: number;
};

const FULL_WIDTH_PERCENT = 100;

/**
 * Scale a row of values against the largest of them.
 *
 * Against the peak rather than a fixed ceiling: the interesting thing about
 * review pressure is which day is the worst one, and a fixed axis flattens
 * that into a row of stubs on a quiet week. An all-zero row draws nothing,
 * which is the honest picture of a week with no reviews.
 */
export function barRow(data: FigureDatum[]): FigureBar[] {
  const peak = data.reduce((max, datum) => Math.max(max, datum.value), 0);
  return data.map((datum) => ({
    ...datum,
    percent:
      peak <= 0 ? 0 : clampPercent((datum.value / peak) * FULL_WIDTH_PERCENT),
  }));
}

/** A 0-1 ratio as a percentage of the figure's width. */
export function ratioPercent(value: number): number {
  return clampPercent(value * FULL_WIDTH_PERCENT);
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value) || value <= 0) {
    return 0;
  }
  return Math.min(value, FULL_WIDTH_PERCENT);
}

export type CalibrationRow = {
  topic: string;
  predicted: number;
  actual: number | null;
  legacyScored: boolean;
};

export type CalibrationSplit = {
  /** Rows a figure may be drawn from. */
  measured: CalibrationRow[];
  /** Rows whose `actual` came from the retired heuristic scorer. */
  legacyScored: CalibrationRow[];
  /** Rows predicted but not yet measured. */
  unmeasured: CalibrationRow[];
};

/**
 * Split calibration rows into what may be drawn and what must be declared.
 *
 * The retired scorer reported an `actual` of 1.0 for anything a learner
 * submitted (#97). Averaging those into a blind-spot figure does not add noise
 * — it produces a confident claim that the learner is perfectly calibrated.
 * They are kept out of the figure and counted where the learner can see them,
 * because silently dropping rows is its own kind of lie.
 */
export function splitCalibrationRows(rows: CalibrationRow[]): CalibrationSplit {
  const split: CalibrationSplit = {
    measured: [],
    legacyScored: [],
    unmeasured: [],
  };
  for (const row of rows) {
    if (row.legacyScored) {
      split.legacyScored.push(row);
    } else if (row.actual === null) {
      split.unmeasured.push(row);
    } else {
      split.measured.push(row);
    }
  }
  return split;
}
