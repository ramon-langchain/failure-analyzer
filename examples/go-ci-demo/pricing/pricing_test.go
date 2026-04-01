package pricing

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestSubtotalCents(t *testing.T) {
	t.Parallel()

	items := []Item{
		{SKU: "hoodie", UnitPriceCents: 4500, Quantity: 1},
		{SKU: "stickers", UnitPriceCents: 250, Quantity: 3},
		{SKU: "invalid-negative", UnitPriceCents: -100, Quantity: 1},
		{SKU: "invalid-zero-qty", UnitPriceCents: 999, Quantity: 0},
	}

	got := SubtotalCents(items)
	want := 5250
	if diff := cmp.Diff(want, got); diff != "" {
		t.Fatalf("SubtotalCents() mismatch (-want +got):\n%s", diff)
	}
}

func TestShippingCents(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name       string
		subtotal   int
		expedited  bool
		wantCents  int
	}{
		{
			name:      "standard shipping below threshold",
			subtotal:  6_500,
			expedited: false,
			wantCents: 599,
		},
		{
			name:      "free standard shipping at threshold",
			subtotal:  10_000,
			expedited: false,
			wantCents: 0,
		},
		{
			name:      "expedited shipping always charged",
			subtotal:  12_500,
			expedited: true,
			wantCents: 1499,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			if got := ShippingCents(tt.subtotal, tt.expedited); got != tt.wantCents {
				t.Fatalf("ShippingCents(%d, %t) = %d, want %d", tt.subtotal, tt.expedited, got, tt.wantCents)
			}
		})
	}
}

func TestTaxCents(t *testing.T) {
	t.Parallel()

	got := TaxCents(1_099, 0.0825)
	if got != 91 {
		t.Fatalf("TaxCents() = %d, want %d", got, 91)
	}
}

func TestTotalCents(t *testing.T) {
	t.Parallel()

	items := []Item{
		{SKU: "notebook", UnitPriceCents: 2_500, Quantity: 2},
		{SKU: "pen", UnitPriceCents: 299, Quantity: 1},
	}

	got := TotalCents(items, 0.10, false)
	want := 5_299 + 599 + 529
	if got != want {
		t.Fatalf("TotalCents() = %d, want %d", got, want)
	}
}
