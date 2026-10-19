import numpy as np
import pytest
import torch

from backend.emg_deep import build_classifier, load_classifier, predict_classifier, save_classifier, train_classifier


@pytest.mark.parametrize("architecture", ["MLP", "CNN_1D", "TCN", "GRU", "CNN_GRU"])
def test_deep_architecture_forward_shape_and_real_parameter_update(architecture):
    torch.manual_seed(3)
    model = build_classifier(architecture, channels=3, samples=32, classes=2)
    values = torch.randn(8, 3, 32)
    before = [parameter.detach().clone() for parameter in model.parameters()]
    logits = model(values.flatten(1)) if architecture == "MLP" else model(values)
    assert logits.shape == (8, 2)
    loss = torch.nn.CrossEntropyLoss()(logits, torch.tensor([0, 1] * 4))
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    optimizer.zero_grad(); loss.backward(); optimizer.step()
    assert any(not torch.equal(old, new) for old, new in zip(before, model.parameters()))


def test_training_loss_decreases_and_checkpoint_predictions_survive_reload(tmp_path):
    rng = np.random.default_rng(8)
    values = rng.normal(size=(30, 1, 32)).astype("float32")
    labels = (values.mean(axis=(1, 2)) > 0).astype("int64")
    trained = train_classifier("MLP", values[:24], labels[:24], values[24:], labels[24:], epochs=30, seed=8)
    history = trained["history"]
    assert history[-1]["training_loss"] < history[0]["training_loss"]
    assert trained["device"] == "cpu"
    expected = predict_classifier(trained["model"], "MLP", values[24:])
    path = tmp_path / "model.pt"
    save_classifier(path, trained["model"], architecture="MLP", channels=1, samples=32, classes=["REST", "ACTIVE"])
    restored, payload = load_classifier(path)
    assert payload["classes"] == ["REST", "ACTIVE"]
    assert np.array_equal(expected, predict_classifier(restored, "MLP", values[24:]))


def test_deep_training_cancellation_is_real():
    values = np.zeros((8, 1, 16), dtype="float32")
    labels = np.asarray([0, 1] * 4)
    with pytest.raises(InterruptedError, match="cancelled"):
        train_classifier("CNN_1D", values[:6], labels[:6], values[6:], labels[6:], epochs=10, seed=1, cancel=lambda: True)


@pytest.mark.parametrize("architecture", ["CNN_1D", "TCN", "GRU", "CNN_GRU"])
def test_temporal_models_execute_real_training_on_cpu(architecture):
    rng = np.random.default_rng(19)
    labels = np.asarray([0, 1] * 8)
    values = rng.normal(0, .03, (16, 1, 24)).astype("float32") + labels[:, None, None] * .8
    trained = train_classifier(architecture, values[:12], labels[:12], values[12:], labels[12:], epochs=8, seed=19)
    assert trained["device"] == "cpu"
    assert len(trained["history"]) > 1
    assert min(row["training_loss"] for row in trained["history"][1:]) < trained["history"][0]["training_loss"]


@pytest.mark.parametrize("architecture", ["CNN_1D", "TCN", "GRU", "CNN_GRU"])
def test_temporal_checkpoint_reload_preserves_predictions(architecture, tmp_path):
    values = np.random.default_rng(31).normal(size=(4, 1, 24)).astype("float32")
    model = build_classifier(architecture, channels=1, samples=24, classes=2)
    expected = predict_classifier(model, architecture, values)
    path = tmp_path / f"{architecture}.pt"
    save_classifier(path, model, architecture=architecture, channels=1, samples=24, classes=["REST", "ACTIVE"])
    restored, _ = load_classifier(path)
    assert np.array_equal(expected, predict_classifier(restored, architecture, values))
