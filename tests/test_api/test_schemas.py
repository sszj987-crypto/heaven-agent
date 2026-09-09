from src.api.schemas import ChatResponse, ChatTiming, LLMSettingsUpdate, MemoryReference


def test_llm_settings_update_distinguishes_omitted_and_clear_key():
    keep = LLMSettingsUpdate(model="gpt-4o-mini")
    clear = LLMSettingsUpdate(api_key="")

    assert "api_key" not in keep.model_fields_set
    assert "api_key" in clear.model_fields_set
    assert clear.api_key == ""


def test_chat_response_exposes_memory_provenance_and_safety_state():
    response = ChatResponse(
        response_text="记得呀",
        instruct_text="温柔地说",
        has_voice=False,
        safety_state="normal",
        used_memories=[
            MemoryReference(
                id="mem_1",
                content="喜欢桂花糕",
                dimension="personal_traits",
                source_type="import",
            )
        ],
    )

    assert response.used_memories[0].source_type == "import"
    assert response.safety_state == "normal"


def test_chat_response_exposes_response_timing():
    response = ChatResponse(
        response_text="记得呀",
        instruct_text="温柔地说",
        has_voice=False,
        timing=ChatTiming(first_response_ms=120, total_response_ms=450),
    )

    assert response.timing.first_response_ms == 120
    assert response.timing.total_response_ms == 450
