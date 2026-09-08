import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'benchmark_run.dart';

typedef TelemetryValue = double? Function(TelemetrySample sample);

class MetricGraphCard extends StatelessWidget {
  const MetricGraphCard({
    required this.title,
    required this.samples,
    required this.value,
    required this.unit,
    required this.color,
    super.key,
  });

  final String title;
  final List<TelemetrySample> samples;
  final TelemetryValue value;
  final String unit;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final values = samples.map(value).whereType<double>().toList();
    final maximum = values.isEmpty ? null : values.reduce(math.max);
    return Card.outlined(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                Text(
                  maximum == null
                      ? 'N/A'
                      : '최대 ${maximum.toStringAsFixed(1)}$unit',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 112,
              width: double.infinity,
              child: values.length < 2
                  ? const Center(child: Text('계측 데이터 부족'))
                  : CustomPaint(
                      painter: _TelemetryChartPainter(
                        samples: samples,
                        value: value,
                        color: color,
                        gridColor: Theme.of(context).colorScheme.outlineVariant,
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TelemetryChartPainter extends CustomPainter {
  _TelemetryChartPainter({
    required this.samples,
    required this.value,
    required this.color,
    required this.gridColor,
  });

  final List<TelemetrySample> samples;
  final TelemetryValue value;
  final Color color;
  final Color gridColor;

  @override
  void paint(Canvas canvas, Size size) {
    final points = samples
        .map((sample) => (sample.elapsedMs.toDouble(), value(sample)))
        .where((point) => point.$2 != null)
        .map((point) => (point.$1, point.$2!))
        .toList();
    if (points.length < 2) return;

    final grid = Paint()
      ..color = gridColor
      ..strokeWidth = 1;
    for (var row = 0; row <= 2; row++) {
      final y = size.height * row / 2;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    final minX = points.first.$1;
    final maxX = math.max(points.last.$1, minX + 1);
    final values = points.map((point) => point.$2);
    final minValue = values.reduce(math.min);
    final maxValue = values.reduce(math.max);
    final range = math.max(
      maxValue - minValue,
      math.max(maxValue.abs() * 0.08, 1),
    );
    final path = Path();
    for (var index = 0; index < points.length; index++) {
      final point = points[index];
      final x = (point.$1 - minX) / (maxX - minX) * size.width;
      final y = size.height - (point.$2 - minValue) / range * size.height;
      if (index == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round,
    );

    for (var index = 1; index < samples.length; index++) {
      if (samples[index - 1].screenInteractive ==
          samples[index].screenInteractive) {
        continue;
      }
      final x = (samples[index].elapsedMs - minX) / (maxX - minX) * size.width;
      canvas.drawLine(
        Offset(x, 0),
        Offset(x, size.height),
        Paint()
          ..color = gridColor
          ..strokeWidth = 1.5,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _TelemetryChartPainter oldDelegate) => true;
}
