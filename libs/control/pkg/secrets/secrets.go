// Package secrets provides AES-256-GCM encryption for secrets at rest.
package secrets

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"io"
	"strings"
)

const encPrefix = "enc:"

// Encryptor encrypts and decrypts secret strings using AES-256-GCM.
// A zero-value Encryptor is valid and acts as a no-op passthrough.
type Encryptor struct {
	key []byte // 32-byte AES-256 key; nil means passthrough
}

// NewEncryptor creates an Encryptor from a secret key string.
// If secretKey is empty, the returned Encryptor is a no-op passthrough
// (secrets are stored in plaintext — suitable for development only).
// Otherwise the key is SHA-256 hashed to produce a stable 32-byte AES key.
func NewEncryptor(secretKey string) *Encryptor {
	secretKey = strings.TrimSpace(secretKey)
	if secretKey == "" {
		return &Encryptor{}
	}
	hash := sha256.Sum256([]byte(secretKey))
	return &Encryptor{key: hash[:]}
}

// Encrypt encrypts a plaintext string. Returns "" for empty input.
// When no key is configured, returns the plaintext unchanged.
func (e *Encryptor) Encrypt(plaintext string) (string, error) {
	if plaintext == "" {
		return "", nil
	}
	if e == nil || e.key == nil {
		return plaintext, nil
	}

	block, err := aes.NewCipher(e.key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}

	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return encPrefix + base64.StdEncoding.EncodeToString(ciphertext), nil
}

// Decrypt decrypts a previously encrypted string. Returns "" for empty input.
// If the value doesn't have the "enc:" prefix, it's returned as-is (plaintext fallback).
func (e *Encryptor) Decrypt(value string) (string, error) {
	if value == "" {
		return "", nil
	}
	if !strings.HasPrefix(value, encPrefix) {
		// Not encrypted — return as plaintext (migration path).
		return value, nil
	}
	if e == nil || e.key == nil {
		return "", errors.New("encrypted value found but no secret key configured")
	}

	data, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(value, encPrefix))
	if err != nil {
		return "", err
	}

	block, err := aes.NewCipher(e.key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	nonceSize := gcm.NonceSize()
	if len(data) < nonceSize {
		return "", errors.New("ciphertext too short")
	}

	nonce, ciphertext := data[:nonceSize], data[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", err
	}
	return string(plaintext), nil
}

// Mask returns a masked version of a secret for display purposes.
// Shows first 4 and last 4 characters if long enough, otherwise all asterisks.
func Mask(value string) string {
	if value == "" {
		return ""
	}
	n := len(value)
	if n <= 8 {
		return strings.Repeat("*", n)
	}
	return value[:4] + strings.Repeat("*", n-8) + value[n-4:]
}
