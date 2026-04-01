package pricing

// Item is a single line item in an order.
type Item struct {
	SKU            string
	UnitPriceCents int
	Quantity       int
}

// SubtotalCents computes the item subtotal before shipping or tax.
func SubtotalCents(items []Item) int {
	total := 0
	for _, item := range items {
		if item.Quantity <= 0 || item.UnitPriceCents < 0 {
			continue
		}
		total += item.UnitPriceCents * item.Quantity
	}
	return total
}

// ShippingCents returns standard or expedited shipping for the order subtotal.
func ShippingCents(subtotalCents int, expedited bool) int {
	if subtotalCents <= 0 {
		return 0
	}

	if expedited {
		return 1499
	}

	if subtotalCents > 10_000 {
		return 0
	}

	return 599
}

// TaxCents computes tax from the subtotal using a decimal rate.
func TaxCents(subtotalCents int, taxRate float64) int {
	if subtotalCents <= 0 || taxRate <= 0 {
		return 0
	}

	return int(float64(subtotalCents) * taxRate)
}

// TotalCents returns the final amount charged to the customer.
func TotalCents(items []Item, taxRate float64, expedited bool) int {
	subtotal := SubtotalCents(items)
	shipping := ShippingCents(subtotal, expedited)
	tax := TaxCents(subtotal, taxRate)
	return subtotal + shipping + tax
}
