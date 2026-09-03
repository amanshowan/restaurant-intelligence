/**
 * Measures derived on the client from figures the API already returned.
 *
 * Kept deliberately small. Anything that needs to agree with a number the
 * backend also computes belongs in the backend, where it can be tested against
 * the database — a second implementation here is a second thing to get wrong.
 * What lives here is arithmetic over values already in hand, following the same
 * rule the backend applies to every ratio it reports.
 */

/**
 * Discounts as a percentage of gross sales.
 *
 * Null — not zero — when gross sales is not positive. The ratio is genuinely
 * UNDEFINED there. `discount_rate_percent` in the menu evidence schema is this
 * same measure and is nullable for this same reason: rendering it as "0.0%"
 * would assert that nothing was discounted, which is a different claim from
 * "there is nothing to divide by".
 */
export function discountRatePercent(
  discountsPence: number,
  grossSalesPence: number,
): number | null {
  if (grossSalesPence <= 0) return null;
  return (discountsPence / grossSalesPence) * 100;
}
