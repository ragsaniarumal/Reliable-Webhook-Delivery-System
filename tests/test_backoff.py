from hookrelay.backoff import exponential_backoff

def test_backoff_caps():
    assert exponential_backoff(1, 2, 10) == 2
    assert exponential_backoff(2, 2, 10) == 4
    assert exponential_backoff(4, 2, 10) == 10
