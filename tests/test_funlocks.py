def test_funlock_response_is_bounded():
    from cogs.core.funlocks import bark_response, uwuify

    result = uwuify("hello friend", seed=1)
    bark = bark_response(seed=2, target_name="Ada")

    assert len(result) <= 1800
    assert result
    assert "hello" not in result
    assert bark
    assert len(bark) <= 1800
