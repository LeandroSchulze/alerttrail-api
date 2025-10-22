{% extends "base.html" %}
{% block content %}
<h1>Pagos</h1>

{% if payments and payments|length %}
<table>
  <thead><tr><th>Fecha</th><th>Método</th><th>Importe</th><th>Estado</th></tr></thead>
  <tbody>
  {% for p in payments %}
    <tr>
      <td>{{ p.created_at }}</td>
      <td>{{ p.provider or "—" }}</td>
      <td>{{ p.amount }} {{ (p.currency or "USD")|upper }}</td>
      <td>{{ p.status }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No hay pagos aún.</p>
{% endif %}

<p class="mt-4">
  <a href="{{ url_for('billing_payments') }}">Últimos pagos</a> ·
  <a href="{{ url_for('billing_payments') }}?all=1">Ver todo el historial</a>
</p>
{% endblock %}
