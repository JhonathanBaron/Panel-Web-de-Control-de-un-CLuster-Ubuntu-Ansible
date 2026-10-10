# Aplicaciones Desplegadas en el Cluster

El cluster I2E ejecuta varias aplicaciones de computo distribuido y ciencia de datos.

## Resumen de servicios

| Aplicacion | Puerto | Nodo | Proposito |
|------------|--------|------|-----------|
| Apache Spark | 8080 (UI), 7077 (master) | manager | Procesamiento de datos distribuido |
| Ray | 8265 (dashboard), 6380 (head) | manager | Computo distribuido + ML |
| JupyterHub | 8888 | manager | Notebooks multiusuario |
| Portainer | 9443 (HTTPS) | manager | Administracion de Docker |

## Apache Spark

Motor de procesamiento de datos distribuido. Permite procesar grandes volumenes de datos en paralelo sobre los workers.

### Instalacion

    cd ~/cluster-i2e
    ansible-playbook -i hosts playbooks/19_spark.yml

### Arranque y parada

    ansible-playbook -i hosts playbooks/19_spark_start.yml
    ansible-playbook -i hosts playbooks/19_spark_stop.yml

### Acceso

- Web UI: http://192.168.1.10:8080
- Master URL: spark://192.168.1.10:7077

### Uso desde PySpark

    from pyspark.sql import SparkSession
    spark = SparkSession.builder \
        .appName("MiApp") \
        .master("spark://192.168.1.10:7077") \
        .getOrCreate()

## Ray

Framework de computo distribuido para Python. Ideal para machine learning distribuido.

### Instalacion

    ansible-playbook -i hosts playbooks/18_ray.yml

### Arranque

    ansible-playbook -i hosts playbooks/18_ray.yml

### Acceso

- Dashboard: http://192.168.1.10:8265
- Head: ray://192.168.1.10:6380

### Uso

    import ray
    ray.init(address="ray://192.168.1.10:6380")

    @ray.remote
    def f(x):
        return x * x

    ray.get([f.remote(i) for i in range(10)])

## JupyterHub

Servidor multiusuario de notebooks Jupyter.

### Instalacion

    ansible-playbook -i hosts playbooks/17_jupyterhub.yml
    ansible-playbook -i hosts playbooks/21_kernels.yml

### Acceso

http://192.168.1.10:8888

Cada usuario inicia sesion con sus credenciales del cluster y accede a sus propios notebooks.

## Portainer

Interfaz web para administrar contenedores Docker.

### Instalacion

    ansible-playbook -i hosts playbooks/03_portainer.yml

### Acceso

https://192.168.1.10:9443

## Docker y Apptainer

    # Instalacion de Docker
    ansible-playbook -i hosts playbooks/02_docker.yml

    # Instalacion de Apptainer (alternativa sin daemon)
    ansible-playbook -i hosts playbooks/16_apptainer.yml

## Control desde el Panel Web

Todos los servicios se pueden arrancar/detener desde la seccion "Aplicaciones" del Panel de Control I2E.

## Verificacion

    # Estado de Spark
    curl -s http://192.168.1.10:8080 | head -20

    # Estado de Ray
    ray status --address=192.168.1.10:6380

    # Estado de JupyterHub
    curl -s http://192.168.1.10:8888/hub/login