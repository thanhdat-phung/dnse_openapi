"""Optional Email OTP automation."""

from .email import EmailOTPReader, OTPTimeout, extract_otp

__all__ = ["EmailOTPReader", "OTPTimeout", "extract_otp"]
