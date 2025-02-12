# Vérificateur de Stock

Vérificateur de Stock est une application Python qui surveille la disponibilité et le prix de produits sur des sites e-commerce populaires tels qu'Amazon, LDLC et Grosbill. L'application propose une interface graphique moderne (PySide6), des vérifications multi-threadées et des alertes personnalisables.

## Fonctionnalités

- **Surveillance Multi-sites**  
  Surveillez les produits sur Amazon, LDLC et Grosbill.

- **Intervalle Personnalisable**  
  Définissez un intervalle de vérification différent pour chaque produit.

- **Gestion du CAPTCHA**  
  Détection des challenges CAPTCHA et résolution manuelle via une boîte de dialogue dédiée.

- **Alertes sur Prix Limite**  
  Spécifiez un prix maximum acceptable et recevez une alerte lorsque le produit est en stock en dessous de ce seuil.

- **Alertes Discord et Sonores**  
  Configurez des notifications via webhook Discord et/ou des alertes sonores.

- **Interface Éditable**  
  Modifiez directement la valeur du prix limite dans le tableau.

- **Configuration Persistante**  
  Les paramètres de l'application sont sauvegardés et chargés via un fichier JSON.
