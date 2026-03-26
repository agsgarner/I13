import argparse
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args():
    parser = argparse.ArgumentParser(description="Generate text from a pretrained Qwen model.")
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--prompt", type=str, default="Design")
    parser.add_argument("--max-new-tokens", type=int, default=200)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    return parser.parse_args()


def main():
    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype=(torch.float16 if torch.cuda.is_available() else torch.float32),
        device_map="auto",
    )

    chat = [
        {
            "role": "system",
            "content": "You are an analog circuit design assistant.",
        },
        {
            "role": "user",
            "content": args.prompt,
        },
    ]

    chat_inputs = tokenizer.apply_chat_template(
        chat,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )

    if isinstance(chat_inputs, torch.Tensor):
        chat_inputs = {"input_ids": chat_inputs}

    chat_inputs = {k: v.to(model.device) for k, v in chat_inputs.items()}

    outputs = model.generate(
        **chat_inputs,
        max_new_tokens=args.max_new_tokens,
        do_sample=True,
        temperature=args.temperature,
        top_p=args.top_p,
        pad_token_id=tokenizer.eos_token_id,
    )

    prompt_len = chat_inputs["input_ids"].shape[1]
    generated_ids = outputs[0][prompt_len:]
    print(tokenizer.decode(generated_ids, skip_special_tokens=True))


if __name__ == "__main__":
    main()
