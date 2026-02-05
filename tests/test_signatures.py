from hookrelay.signatures import sign_payload, verify_signature

def test_signature_round_trip():
    secret = "super-secret"
    body = b'{"x":1}'
    sig = sign_payload(secret, 123, body)
    assert verify_signature(secret, 123, body, sig)
    assert not verify_signature(secret, 123, b'{"x":2}', sig)
