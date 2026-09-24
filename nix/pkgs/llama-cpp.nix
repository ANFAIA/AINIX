# llama.cpp at the same build the development runner uses (b11151).
#
# nixpkgs 25.05 ships b5311, from May 2025. It cannot load Qwen3.5 —
# `unknown model architecture: 'qwen35'` — which is most of the catalog's small
# tier and every model this repo has fine-tuned. The image and the laptop must
# serve with the same engine, or a model that passes `make smoke` fails on the
# distribution it was trained for.
final: prev: {
  llama-cpp = prev.llama-cpp.overrideAttrs (old: {
    version = "11151";
    src = prev.fetchFromGitHub {
      owner = "ggml-org";
      repo = "llama.cpp";
      tag = "b11151";
      hash = "sha256-iYK2+ukOODgTMSO9shS4l5dSJ1jnVYy78W+EDdUq+Nk=";
    };
  });
}
