import argparse
from pathlib import Path

import torch

from train_transformer import CharTransformerLM, PositionalEncoding  # noqa: F401


def parse_args():
    parser = argparse.ArgumentParser(description="Generate text from a trained char Transformer.")
    parser.add_argument("--checkpoint", type=Path, default=Path("char_transformer.pt"))
    parser.add_argument("--prompt", type=str, default="Design")
    parser.add_argument("--max-new-tokens", type=int, default=200)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-k", type=int, default=0)
    return parser.parse_args()


def sample_next_token(logits: torch.Tensor, temperature: float, top_k: int) -> int:
    logits = logits / max(temperature, 1e-6)
    if top_k > 0:
        values, _ = torch.topk(logits, k=min(top_k, logits.numel()))
        threshold = values[-1]
        logits = torch.where(logits < threshold, torch.full_like(logits, float("-inf")), logits)
    probs = torch.softmax(logits, dim=-1)
    return torch.multinomial(probs, num_samples=1).item()


def main():
    args = parse_args()
    if not args.checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint not found: {args.checkpoint}")

    ckpt = torch.load(args.checkpoint, map_location="cpu")
    stoi = ckpt["stoi"]
    itos = ckpt["itos"]
    config = ckpt["config"]

    model = CharTransformerLM(
        vocab_size=len(stoi),
        d_model=config["d_model"],
        nhead=config["nhead"],
        num_layers=config["num_layers"],
        ff_dim=config["ff_dim"],
        dropout=config["dropout"],
    )
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    # Drop OOV prompt characters so generation always starts from known tokens.
    prompt_ids = [stoi[ch] for ch in args.prompt if ch in stoi]
    if not prompt_ids:
        raise ValueError("Prompt has no characters present in training vocabulary.")

    generated = torch.tensor(prompt_ids, dtype=torch.long).unsqueeze(0)
    block_size = config["block_size"]

    with torch.no_grad():
        for _ in range(args.max_new_tokens):
            context = generated[:, -block_size:]
            logits = model(context)
            next_token = sample_next_token(
                logits[0, -1],
                temperature=args.temperature,
                top_k=args.top_k,
            )
            next_token_t = torch.tensor([[next_token]], dtype=torch.long)
            generated = torch.cat((generated, next_token_t), dim=1)

    text_out = "".join(itos[i] for i in generated[0].tolist())
    print(text_out)


if __name__ == "__main__":
    main()
