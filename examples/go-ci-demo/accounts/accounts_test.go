package accounts

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestNormalizeEmail(t *testing.T) {
	t.Parallel()

	got := NormalizeEmail("  SUPPORT@Example.COM  ")
	want := "support@example.com"
	if diff := cmp.Diff(want, got); diff != "" {
		t.Fatalf("NormalizeEmail() mismatch (-want +got):\n%s", diff)
	}
}

func TestCanRetryLogin(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name string
		user User
		want bool
	}{
		{
			name: "verified user under threshold",
			user: User{EmailVerified: true, FailedLogins: 2},
			want: true,
		},
		{
			name: "verified user locked after too many failures",
			user: User{EmailVerified: true, FailedLogins: 5},
			want: false,
		},
		{
			name: "unverified user blocked",
			user: User{EmailVerified: false, FailedLogins: 0},
			want: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			if got := CanRetryLogin(tt.user); got != tt.want {
				t.Fatalf("CanRetryLogin(%+v) = %t, want %t", tt.user, got, tt.want)
			}
		})
	}
}

func TestPrimaryDomain(t *testing.T) {
	t.Parallel()

	got := PrimaryDomain("alerts@payments.internal")
	want := "payments.internal"
	if diff := cmp.Diff(want, got); diff != "" {
		t.Fatalf("PrimaryDomain() mismatch (-want +got):\n%s", diff)
	}
}
