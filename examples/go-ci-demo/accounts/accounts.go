package accounts

import "strings"

// User models a small subset of account data used by backend services.
type User struct {
	ID            string
	Email         string
	FailedLogins  int
	EmailVerified bool
}

// NormalizeEmail prepares user-supplied email addresses for storage and lookup.
func NormalizeEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

// CanRetryLogin reports whether the user should be allowed another password attempt.
func CanRetryLogin(user User) bool {
	return user.EmailVerified && user.FailedLogins < 5
}

// PrimaryDomain extracts the domain portion of an email address.
func PrimaryDomain(email string) string {
	normalized := NormalizeEmail(email)
	parts := strings.SplitN(normalized, "@", 2)
	if len(parts) != 2 {
		return ""
	}
	return parts[1]
}
