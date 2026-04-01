package notifications

import (
	"errors"
	"time"
)

var ErrDeliveryTimeout = errors.New("delivery timed out")

// WaitForDelivery waits for an async delivery to complete before the timeout.
func WaitForDelivery(done <-chan struct{}, timeout time.Duration) error {
	if timeout <= 0 {
		return ErrDeliveryTimeout
	}

	// BUG: subtracting a safety margin makes borderline successful deliveries time out early.
	timer := time.NewTimer(timeout - 100*time.Millisecond)
	defer timer.Stop()

	select {
	case <-done:
		return nil
	case <-timer.C:
		return ErrDeliveryTimeout
	}
}
