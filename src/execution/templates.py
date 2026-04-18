from __future__ import annotations

"""
ScholarMind - 通信领域代码模板管理器
=========================================

功能：
  1. 提供通信/信号处理领域的 starter 代码模板
  2. 每个模板是一个可执行的 Python 脚本片段
  3. Agent 可以基于模板快速生成论文方法的仿真代码

【工程思考】模板 vs 代码生成：
  - 纯 LLM 生成代码容易遗漏细节（如 FFT 点数、CP 长度）
  - 模板提供正确的骨架 + 典型参数，LLM 只需"填空"
  - 降低幻觉风险：LLM 修改模板比从零写更可靠

【模板设计原则】：
  1. 每个模板都是可独立运行的完整脚本
  2. 参数在顶部，一目了然
  3. 自带 matplotlib 可视化输出
  4. 注释密集（中英双语），方便理解
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("ScholarMind.Templates")


@dataclass
class CodeTemplate:
    """代码模板"""
    name: str               # 模板名（如 "ofdm_basic"）
    title: str              # 人类可读标题
    description: str        # 功能描述
    category: str           # 分类（signal_processing / communication / localization）
    code: str               # 完整代码
    parameters: list[str]   # 可调参数列表
    difficulty: str         # easy / medium / hard


# ============================================================
# 模板库
# ============================================================

TEMPLATES: dict[str, CodeTemplate] = {}


def _register(template: CodeTemplate):
    TEMPLATES[template.name] = template
    return template


# -----------------------------------------------------------
# 1. OFDM 基础仿真
# -----------------------------------------------------------
_register(CodeTemplate(
    name="ofdm_basic",
    title="OFDM 基础收发机仿真",
    description=(
        "完整的 OFDM 系统仿真：QPSK 调制 → IFFT → 加 CP → AWGN 信道 → "
        "去 CP → FFT → 解调 → BER 计算。包含星座图和 BER 曲线。"
    ),
    category="communication",
    parameters=["N_subcarriers", "CP_length", "SNR_range", "modulation_order"],
    difficulty="easy",
    code='''"""
OFDM Basic Transceiver Simulation
==================================
完整的 OFDM 系统仿真，包含：
- QPSK 调制/解调
- IFFT/FFT 变换
- 循环前缀 (CP) 添加/去除
- AWGN 信道
- BER 性能曲线

Modify parameters below to experiment.
"""
import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# Parameters (修改这里的参数来实验)
# ============================================================
N_sc = 64          # Number of subcarriers (子载波数)
CP_len = 16        # Cyclic prefix length (循环前缀长度)
N_symbols = 1000   # Number of OFDM symbols (OFDM 符号数)
SNR_dB_range = np.arange(0, 21, 2)  # SNR range in dB

# ============================================================
# QPSK Modulation
# ============================================================
def qpsk_mod(bits):
    """QPSK modulation: 2 bits -> 1 complex symbol"""
    symbols = (1 - 2*bits[0::2]) + 1j*(1 - 2*bits[1::2])
    return symbols / np.sqrt(2)

def qpsk_demod(symbols):
    """QPSK demodulation: 1 complex symbol -> 2 bits"""
    bits = np.zeros(2 * len(symbols), dtype=int)
    bits[0::2] = (np.real(symbols) < 0).astype(int)
    bits[1::2] = (np.imag(symbols) < 0).astype(int)
    return bits

# ============================================================
# OFDM Transceiver
# ============================================================
ber_results = []

for snr_dB in SNR_dB_range:
    n_errors = 0
    n_total = 0

    for _ in range(N_symbols):
        # 1. Generate random bits
        tx_bits = np.random.randint(0, 2, N_sc * 2)

        # 2. QPSK modulation
        tx_symbols = qpsk_mod(tx_bits)

        # 3. IFFT (频域 → 时域)
        tx_time = np.fft.ifft(tx_symbols, N_sc)

        # 4. Add cyclic prefix
        tx_cp = np.concatenate([tx_time[-CP_len:], tx_time])

        # 5. AWGN channel
        snr_linear = 10**(snr_dB / 10)
        noise_power = 1 / (2 * snr_linear)
        noise = np.sqrt(noise_power) * (
            np.random.randn(len(tx_cp)) + 1j*np.random.randn(len(tx_cp))
        )
        rx_cp = tx_cp + noise

        # 6. Remove CP
        rx_time = rx_cp[CP_len:]

        # 7. FFT (时域 → 频域)
        rx_symbols = np.fft.fft(rx_time, N_sc)

        # 8. QPSK demodulation
        rx_bits = qpsk_demod(rx_symbols)

        # 9. Count errors
        n_errors += np.sum(tx_bits != rx_bits)
        n_total += len(tx_bits)

    ber = n_errors / n_total
    ber_results.append(ber)
    print(f"SNR = {snr_dB:2d} dB, BER = {ber:.6f}")

# ============================================================
# Plot Results
# ============================================================
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# BER curve
axes[0].semilogy(SNR_dB_range, ber_results, 'bo-', linewidth=2, markersize=6)
# Theoretical QPSK BER
from scipy.special import erfc
theoretical_ber = 0.5 * erfc(np.sqrt(10**(SNR_dB_range/10)))
axes[0].semilogy(SNR_dB_range, theoretical_ber, 'r--', linewidth=1.5, label='Theoretical')
axes[0].set_xlabel('SNR (dB)')
axes[0].set_ylabel('BER')
axes[0].set_title('OFDM QPSK BER Performance')
axes[0].legend(['Simulated', 'Theoretical'])
axes[0].grid(True)
axes[0].set_ylim([1e-5, 1])

# Constellation at SNR=10dB
snr_demo = 10
tx_bits_demo = np.random.randint(0, 2, N_sc * 2)
tx_sym_demo = qpsk_mod(tx_bits_demo)
noise_demo = np.sqrt(1/(2*10**(snr_demo/10))) * (
    np.random.randn(N_sc) + 1j*np.random.randn(N_sc)
)
rx_sym_demo = tx_sym_demo + noise_demo

axes[1].scatter(np.real(rx_sym_demo), np.imag(rx_sym_demo), alpha=0.5, s=10)
axes[1].scatter(np.real(tx_sym_demo), np.imag(tx_sym_demo), c='red', s=50, marker='x')
axes[1].set_xlabel('In-Phase')
axes[1].set_ylabel('Quadrature')
axes[1].set_title(f'QPSK Constellation (SNR={snr_demo}dB)')
axes[1].grid(True)
axes[1].set_aspect('equal')
axes[1].set_xlim([-2, 2])
axes[1].set_ylim([-2, 2])

plt.tight_layout()
print("\\nSimulation complete. Figure saved.")
''',
))


# -----------------------------------------------------------
# 2. MIMO 波束赋形
# -----------------------------------------------------------
_register(CodeTemplate(
    name="mimo_beamforming",
    title="MIMO 波束赋形仿真",
    description=(
        "ULA 天线阵列的波束赋形：MRT (Maximum Ratio Transmission) 和 "
        "ZF (Zero-Forcing) 预编码对比，包含波束方向图和容量曲线。"
    ),
    category="communication",
    parameters=["N_antennas", "N_users", "SNR_range", "d_lambda"],
    difficulty="medium",
    code='''"""
MIMO Beamforming Simulation
============================
Compare MRT and ZF precoding for multi-user MIMO.
Includes beam pattern and sum-rate capacity curves.
"""
import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# Parameters
# ============================================================
N_tx = 8       # Number of transmit antennas (发射天线数)
N_users = 2    # Number of users (用户数)
d_lambda = 0.5 # Antenna spacing in wavelengths (天线间距/波长)
SNR_dB_range = np.arange(-5, 26, 2)

# ============================================================
# Steering Vector
# ============================================================
def steering_vector(theta, N, d=0.5):
    """ULA steering vector for angle theta (radians)"""
    n = np.arange(N)
    return np.exp(-1j * 2 * np.pi * d * n * np.sin(theta)) / np.sqrt(N)

# User angles (用户方向)
user_angles_deg = [-30, 20]  # degrees
user_angles = np.deg2rad(user_angles_deg)

# Channel matrix (each row is one user's channel)
H = np.array([steering_vector(theta, N_tx, d_lambda) for theta in user_angles])

# ============================================================
# Precoding
# ============================================================
# MRT (Maximum Ratio Transmission)
W_mrt = H.conj().T  # N_tx x N_users
W_mrt = W_mrt / np.linalg.norm(W_mrt, axis=0, keepdims=True)

# ZF (Zero-Forcing)
W_zf = H.conj().T @ np.linalg.inv(H @ H.conj().T)
W_zf = W_zf / np.linalg.norm(W_zf, axis=0, keepdims=True)

# ============================================================
# Beam Patterns
# ============================================================
theta_scan = np.linspace(-np.pi/2, np.pi/2, 361)

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

for user_idx in range(N_users):
    gain_mrt = np.array([
        np.abs(steering_vector(t, N_tx, d_lambda).conj() @ W_mrt[:, user_idx])**2
        for t in theta_scan
    ])
    gain_zf = np.array([
        np.abs(steering_vector(t, N_tx, d_lambda).conj() @ W_zf[:, user_idx])**2
        for t in theta_scan
    ])

    axes[0].plot(np.rad2deg(theta_scan), 10*np.log10(gain_mrt + 1e-10), label=f'User {user_idx+1}')
    axes[1].plot(np.rad2deg(theta_scan), 10*np.log10(gain_zf + 1e-10), label=f'User {user_idx+1}')

for ax, title in zip(axes, ['MRT Beam Pattern', 'ZF Beam Pattern']):
    ax.set_xlabel('Angle (degrees)')
    ax.set_ylabel('Gain (dB)')
    ax.set_title(title)
    ax.legend()
    ax.grid(True)
    ax.set_xlim([-90, 90])
    ax.set_ylim([-30, 5])
    for angle in user_angles_deg:
        ax.axvline(x=angle, color='r', linestyle='--', alpha=0.5)

plt.tight_layout()

# ============================================================
# Sum-Rate Capacity
# ============================================================
fig2, ax2 = plt.subplots(figsize=(8, 5))

capacity_mrt = []
capacity_zf = []

for snr_dB in SNR_dB_range:
    snr = 10**(snr_dB/10) / N_users  # Per-user power

    # MRT capacity (with interference)
    rate_mrt = 0
    for k in range(N_users):
        signal = snr * np.abs(H[k] @ W_mrt[:, k])**2
        interference = sum(
            snr * np.abs(H[k] @ W_mrt[:, j])**2
            for j in range(N_users) if j != k
        )
        rate_mrt += np.log2(1 + signal / (interference + 1))
    capacity_mrt.append(rate_mrt)

    # ZF capacity (no interference)
    rate_zf = 0
    for k in range(N_users):
        signal = snr * np.abs(H[k] @ W_zf[:, k])**2
        rate_zf += np.log2(1 + signal)
    capacity_zf.append(rate_zf)

ax2.plot(SNR_dB_range, capacity_mrt, 'b-o', label='MRT', markersize=4)
ax2.plot(SNR_dB_range, capacity_zf, 'r-s', label='ZF', markersize=4)
ax2.set_xlabel('SNR (dB)')
ax2.set_ylabel('Sum Rate (bits/s/Hz)')
ax2.set_title(f'Sum-Rate Capacity ({N_tx} Tx, {N_users} Users)')
ax2.legend()
ax2.grid(True)

print(f"MIMO Beamforming simulation: {N_tx} antennas, {N_users} users")
print(f"User angles: {user_angles_deg} degrees")
print(f"ZF advantage over MRT at high SNR: ~{capacity_zf[-1]-capacity_mrt[-1]:.1f} bits/s/Hz")
''',
))


# -----------------------------------------------------------
# 3. AOA 估计 (MUSIC 算法)
# -----------------------------------------------------------
_register(CodeTemplate(
    name="aoa_music",
    title="MUSIC 算法 AOA 估计",
    description=(
        "经典 MUSIC (MUltiple SIgnal Classification) 算法的 AOA 估计实现。"
        "包含空间谱估计、峰值检测和角度估计精度分析。"
    ),
    category="localization",
    parameters=["N_antennas", "N_sources", "true_angles", "SNR", "N_snapshots"],
    difficulty="medium",
    code='''"""
MUSIC Algorithm for AOA Estimation
=====================================
Classic MUSIC spatial spectrum estimation.
- ULA array with configurable antenna count
- Multiple source detection
- Spatial spectrum visualization
"""
import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# Parameters
# ============================================================
N_ant = 8           # Number of antennas (天线数)
N_sources = 2       # Number of signal sources (信号源数)
true_angles = [20, -35]  # True angles in degrees (真实角度)
SNR_dB = 10         # Signal-to-Noise Ratio (信噪比)
N_snapshots = 200   # Number of snapshots (快拍数)
d_lambda = 0.5      # Antenna spacing / wavelength (天线间距)

# ============================================================
# Signal Generation
# ============================================================
def steering_vector(theta_deg, N, d=0.5):
    """ULA steering vector"""
    theta = np.deg2rad(theta_deg)
    n = np.arange(N)
    return np.exp(-1j * 2 * np.pi * d * n * np.sin(theta))

# Steering matrix
A = np.column_stack([steering_vector(a, N_ant, d_lambda) for a in true_angles])

# Source signals (uncorrelated)
S = (np.random.randn(N_sources, N_snapshots) +
     1j * np.random.randn(N_sources, N_snapshots)) / np.sqrt(2)

# Received signal
noise_power = 10**(-SNR_dB/10)
noise = np.sqrt(noise_power/2) * (
    np.random.randn(N_ant, N_snapshots) +
    1j * np.random.randn(N_ant, N_snapshots)
)
X = A @ S + noise  # N_ant x N_snapshots

# ============================================================
# MUSIC Algorithm
# ============================================================
# 1. Estimate covariance matrix
R = (X @ X.conj().T) / N_snapshots

# 2. Eigendecomposition
eigenvalues, eigenvectors = np.linalg.eigh(R)
# Sort in descending order
idx = np.argsort(eigenvalues)[::-1]
eigenvalues = eigenvalues[idx]
eigenvectors = eigenvectors[:, idx]

# 3. Noise subspace (last N_ant - N_sources eigenvectors)
En = eigenvectors[:, N_sources:]

# 4. MUSIC spatial spectrum
theta_scan = np.linspace(-90, 90, 1801)
spectrum = np.zeros(len(theta_scan))

for i, theta in enumerate(theta_scan):
    a = steering_vector(theta, N_ant, d_lambda)
    denominator = a.conj() @ En @ En.conj().T @ a
    spectrum[i] = 1 / np.abs(denominator)

spectrum_dB = 10 * np.log10(spectrum / spectrum.max())

# 5. Peak detection
from scipy.signal import find_peaks
peaks, _ = find_peaks(spectrum_dB, height=-10, distance=20)
estimated_angles = theta_scan[peaks]

print("=== MUSIC AOA Estimation ===")
print(f"True angles:      {true_angles}")
print(f"Estimated angles:  {[f'{a:.1f}' for a in estimated_angles[:N_sources]]}")
if len(estimated_angles) >= N_sources:
    errors = [min(abs(e - t) for t in true_angles) for e in estimated_angles[:N_sources]]
    print(f"Estimation errors: {[f'{e:.2f}°' for e in errors]}")

# ============================================================
# Visualization
# ============================================================
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Spatial spectrum
axes[0].plot(theta_scan, spectrum_dB, 'b-', linewidth=1.5)
for angle in true_angles:
    axes[0].axvline(x=angle, color='r', linestyle='--', alpha=0.7, label=f'True: {angle}°')
if len(estimated_angles) > 0:
    axes[0].plot(estimated_angles[:N_sources],
                 spectrum_dB[peaks[:N_sources]], 'rv', markersize=10)
axes[0].set_xlabel('Angle (degrees)')
axes[0].set_ylabel('Spectrum (dB)')
axes[0].set_title(f'MUSIC Spatial Spectrum (SNR={SNR_dB}dB, {N_ant} antennas)')
axes[0].legend()
axes[0].grid(True)
axes[0].set_xlim([-90, 90])

# Eigenvalue distribution
axes[1].stem(range(1, N_ant+1), eigenvalues, linefmt='b-', markerfmt='bo', basefmt='k-')
axes[1].axhline(y=eigenvalues[N_sources], color='r', linestyle='--',
                label=f'Noise floor (N_sources={N_sources})')
axes[1].set_xlabel('Eigenvalue Index')
axes[1].set_ylabel('Eigenvalue')
axes[1].set_title('Eigenvalue Distribution')
axes[1].legend()
axes[1].grid(True)

plt.tight_layout()
print("\\nSimulation complete.")
''',
))


# ============================================================
# 模板管理 API
# ============================================================

def get_template(name: str) -> Optional[CodeTemplate]:
    """获取模板"""
    return TEMPLATES.get(name)


def list_templates(category: str = "") -> list[CodeTemplate]:
    """列出所有模板（可按分类过滤）"""
    if category:
        return [t for t in TEMPLATES.values() if t.category == category]
    return list(TEMPLATES.values())


def get_template_code(name: str, **overrides) -> Optional[str]:
    """
    获取模板代码，支持参数覆盖

    【工程思考】为什么支持参数覆盖？
    Agent 可以根据论文中的具体参数修改模板：
    "这篇论文用的是 128 子载波的 OFDM，帮我改一下模板跑出结果"

    目前用简单的字符串替换实现，后续可升级到 Jinja2
    """
    template = TEMPLATES.get(name)
    if not template:
        return None

    code = template.code
    for key, value in overrides.items():
        # 简单的参数替换（匹配 "param_name = old_value" 模式）
        import re
        pattern = rf"({key}\s*=\s*)(.*?)(\s*#.*)?$"
        replacement = rf"\g<1>{value}\3"
        code = re.sub(pattern, replacement, code, count=1, flags=re.MULTILINE)

    return code
