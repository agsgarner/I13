import argparse
import math
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset


class CharSequenceDataset(Dataset):
    def __init__(self, token_tensor: torch.Tensor, block_size: int):
        if token_tensor.numel() <= block_size:
            raise ValueError(
                f"Dataset too small: need more than {block_size} tokens, got {token_tensor.numel()}."
            )
        self.tokens = token_tensor
        self.block_size = block_size

    def __len__(self) -> int:
        return self.tokens.size(0) - self.block_size

    def __getitem__(self, idx: int):
        x = self.tokens[idx : idx + self.block_size]
        y = self.tokens[idx + 1 : idx + self.block_size + 1]
        return x, y


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 8192):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float)
            * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class CharTransformerLM(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        d_model: int,
        nhead: int,
        num_layers: int,
        ff_dim: int,
        dropout: float,
    ):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, d_model)
        self.position = PositionalEncoding(d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=ff_dim,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.lm_head = nn.Linear(d_model, vocab_size)

    def _causal_mask(self, seq_len: int, device: torch.device) -> torch.Tensor:
        # Prevent attention from seeing future tokens.
        return torch.triu(
            torch.full((seq_len, seq_len), float("-inf"), device=device), diagonal=1
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.embedding(x)
        h = self.position(h)
        mask = self._causal_mask(x.size(1), x.device)
        h = self.encoder(h, mask=mask)
        return self.lm_head(h)


def read_text(data_path: Path) -> str:
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")
    text = data_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Dataset is empty: {data_path}")
    return text


def build_vocab(text: str):
    chars = sorted(set(text))
    stoi = {ch: i for i, ch in enumerate(chars)}
    itos = {i: ch for ch, i in stoi.items()}
    return stoi, itos


def encode_text(text: str, stoi: dict) -> torch.Tensor:
    return torch.tensor([stoi[c] for c in text], dtype=torch.long)


def split_tokens(tokens: torch.Tensor, train_ratio: float):
    split_idx = int(tokens.size(0) * train_ratio)
    split_idx = max(1, min(split_idx, tokens.size(0) - 1))
    return tokens[:split_idx], tokens[split_idx:]


def evaluate(model, loader, loss_fn, device, vocab_size):
    model.eval()
    total_loss = 0.0
    steps = 0
    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            logits = model(xb)
            loss = loss_fn(logits.reshape(-1, vocab_size), yb.reshape(-1))
            total_loss += loss.item()
            steps += 1
    if steps == 0:
        return float("inf")
    return total_loss / steps


def parse_args():
    parser = argparse.ArgumentParser(description="Train a character-level Transformer LM.")
    parser.add_argument("--data", type=Path, default=Path("data/corpus.txt"))
    parser.add_argument("--output", type=Path, default=Path("char_transformer.pt"))
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--train-ratio", type=float, default=0.9)
    parser.add_argument("--d-model", type=int, default=256)
    parser.add_argument("--nhead", type=int, default=8)
    parser.add_argument("--num-layers", type=int, default=4)
    parser.add_argument("--ff-dim", type=int, default=512)
    parser.add_argument("--dropout", type=float, default=0.1)
    return parser.parse_args()


def main():
    args = parse_args()

    text = read_text(args.data)
    stoi, itos = build_vocab(text)
    tokens = encode_text(text, stoi)
    train_tokens, val_tokens = split_tokens(tokens, args.train_ratio)

    train_ds = CharSequenceDataset(train_tokens, args.block_size)
    val_ds = CharSequenceDataset(val_tokens, args.block_size)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = CharTransformerLM(
        vocab_size=len(stoi),
        d_model=args.d_model,
        nhead=args.nhead,
        num_layers=args.num_layers,
        ff_dim=args.ff_dim,
        dropout=args.dropout,
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss()

    print(f"Training on device: {device}")
    print(f"Vocabulary size: {len(stoi)}")
    print(f"Train examples: {len(train_ds)}, Val examples: {len(val_ds)}")

    best_val_loss = float("inf")
    best_state = None

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_train_loss = 0.0
        steps = 0

        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)

            logits = model(xb)
            loss = loss_fn(logits.reshape(-1, len(stoi)), yb.reshape(-1))

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_train_loss += loss.item()
            steps += 1

        train_loss = total_train_loss / max(1, steps)
        val_loss = evaluate(model, val_loader, loss_fn, device, len(stoi))

        print(
            f"Epoch {epoch}/{args.epochs} | train_loss={train_loss:.4f} | val_loss={val_loss:.4f}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    checkpoint = {
        "model_state_dict": model.state_dict(),
        "stoi": stoi,
        "itos": itos,
        "config": {
            "block_size": args.block_size,
            "d_model": args.d_model,
            "nhead": args.nhead,
            "num_layers": args.num_layers,
            "ff_dim": args.ff_dim,
            "dropout": args.dropout,
        },
        "best_val_loss": best_val_loss,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(checkpoint, args.output)
    print(f"Saved checkpoint: {args.output}")


if __name__ == "__main__":
    main()
