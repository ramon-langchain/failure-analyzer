package notifications

import (
	"errors"
	"testing"
	"testing/synctest"
	"time"
)

func TestWaitForDeliveryImmediate(t *testing.T) {
	t.Parallel()

	synctest.Test(t, func(t *testing.T) {
		done := make(chan struct{})
		close(done)

		if err := WaitForDelivery(done, time.Second); err != nil {
			t.Fatalf("WaitForDelivery() returned %v, want nil", err)
		}
	})
}

func TestWaitForDeliveryTimesOut(t *testing.T) {
	t.Parallel()

	synctest.Test(t, func(t *testing.T) {
		done := make(chan struct{})

		err := WaitForDelivery(done, 500*time.Millisecond)
		if !errors.Is(err, ErrDeliveryTimeout) {
			t.Fatalf("WaitForDelivery() error = %v, want %v", err, ErrDeliveryTimeout)
		}
	})
}

func TestWaitForDeliveryHonorsFullTimeout(t *testing.T) {
	t.Parallel()

	synctest.Test(t, func(t *testing.T) {
		done := make(chan struct{})

		go func() {
			time.Sleep(950 * time.Millisecond)
			close(done)
		}()

		if err := WaitForDelivery(done, time.Second); err != nil {
			t.Fatalf("WaitForDelivery() returned %v, want nil for a delivery before the full timeout", err)
		}
	})
}
