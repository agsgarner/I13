from pydantic import BaseModel, Field, HttpUrl, model_validator, ValidationError
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
import os

# Re-using the previously defined helper models
# StorageLocation, DataVersionInfo, and DataArtifact

# Helper Models (copying for self-contained code block, assuming they are already defined and correct in previous cells)
class StorageLocation(BaseModel):
    """Represents a storage location for a data artifact."""
    local_path: Optional[str] = Field(None, description="Local file system path.")
    cloud_url: Optional[str] = Field(None, description="URL for cloud storage (e.g., S3, GCS).")

    @model_validator(mode='after')
    def check_at_least_one_location(self) -> 'StorageLocation':
        if self.local_path is None and self.cloud_url is None:
            raise ValueError('At least one of local_path or cloud_url must be provided.')
        return self


class DataVersionInfo(BaseModel):
    """Represents versioning information for a data artifact."""
    git_repo_url: Optional[HttpUrl] = Field(None, description="URL of the Git repository.")
    commit_hash: Optional[str] = Field(None, description="Specific Git commit hash.")
    branch_name: Optional[str] = Field(None, description="Git branch name.")
    version_timestamp: Optional[datetime] = Field(None, description="Timestamp of the data version.")
    data_version_id: Optional[str] = Field(None, description="Unique identifier for data versioning systems (e.g., DVC, MLflow).")
    description: Optional[str] = Field(None, description="A brief description of the version changes or purpose.")


class DataArtifact(BaseModel):
    """Base model for any data artifact managed by the system."""
    name: str = Field(..., description="A unique name for the data artifact.")
    description: Optional[str] = Field(None, description="Detailed description of the artifact.")
    artifact_type: str = Field(..., description="The type of the data artifact (e.g., 'dataset', 'model_weights', 'source_code').")
    storage: StorageLocation = Field(..., description="The storage location details for the artifact.")
    version_info: Optional[DataVersionInfo] = Field(None, description="Versioning details for the artifact.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional key-value pairs for artifact-specific metadata.")


class DataStorageAgent(BaseModel):
    """Pydantic model for the 'Data Storage and Version Control Subsystem' agent.
    Manages various data types, storage locations, and versioning information.
    """
    agent_name: str = Field("DataStorageAgent", description="Name of the data storage agent.")
    datasets: List[DataArtifact] = Field([], description="List of raw and processed datasets.")
    simulation_results: List[DataArtifact] = Field([], description="List of simulation inputsa and outputs.")
    model_weights: List[DataArtifact] = Field([], description="List of trained model weights and checkpoints.")
    generated_embeddings: List[DataArtifact] = Field([], description="List of generated embeddings.")
    source_code: List[DataArtifact] = Field([], description="List of source code, scripts, and configuration files.")
    logs_metrics_metadata: List[DataArtifact] = Field([], description="List of logs, metrics, and general metadata artifacts.")
    additional_data: List[DataArtifact] = Field([], description="Any other data artifacts not categorized above.")

    system_metadata: Optional[Dict[str, Any]] = Field(None, description="Overall metadata for the data storage and version control system.")

    def store_data(self, artifact: DataArtifact, is_new_version: bool = False) -> Dict[str, Any]:
        """
        Stores a data artifact to its specified location.
        If `is_new_version` is True, it implies an update to an existing artifact.
        """
        print(f"Storing artifact: {artifact.name} (New Version: {is_new_version})")
        # Placeholder for actual storage logic (e.g., S3 upload, local file write)
        # This would involve checking artifact.storage.local_path or artifact.storage.cloud_url
        # and performing the appropriate I/O operation.
        # For now, just print a confirmation.

        # Example of how it might handle different storage types
        if artifact.storage.local_path:
            print(f"  - Saving locally to: {artifact.storage.local_path}")
            # Simulate file write
            # with open(artifact.storage.local_path, 'wb') as f: f.write(b'dummy_data')
        if artifact.storage.cloud_url:
            print(f"  - Uploading to cloud: {artifact.storage.cloud_url}")
            # Simulate cloud upload via an API call
            # cloud_service.upload(artifact.storage.cloud_url, data)

        # Add artifact to the relevant list in the agent model
        if artifact.artifact_type == 'dataset':
            self.datasets.append(artifact)
        elif artifact.artifact_type == 'model_weights':
            self.model_weights.append(artifact)
        elif artifact.artifact_type == 'source_code':
            self.source_code.append(artifact)
        elif artifact.artifact_type == 'simulation_results':
            self.simulation_results.append(artifact)
        elif artifact.artifact_type == 'generated_embeddings':
            self.generated_embeddings.append(artifact)
        elif artifact.artifact_type == 'logs_metrics_metadata':
            self.logs_metrics_metadata.append(artifact)
        else:
            self.additional_data.append(artifact)

        return {"status": "success", "message": f"Artifact {artifact.name} stored successfully."}

    def retrieve_data(self, name: str, version_id: Optional[str] = None,
                      artifact_type: Optional[str] = None) -> Optional[DataArtifact]:
        """
        Retrieves a data artifact by name and optional version/type.
        Returns the DataArtifact object or None if not found.
        """
        print(f"Retrieving artifact: {name}, Version: {version_id}, Type: {artifact_type}")
        # Placeholder for actual retrieval logic
        # This would iterate through the lists of DataArtifacts and match based on criteria.
        # For now, simulate finding a matching artifact.
        all_artifacts = (
            self.datasets + self.simulation_results + self.model_weights +
            self.generated_embeddings + self.source_code + self.logs_metrics_metadata +
            self.additional_data
        )

        for art in all_artifacts:
            if art.name == name:
                if artifact_type is None or art.artifact_type == artifact_type:
                    if version_id is None or (art.version_info and art.version_info.data_version_id == version_id):
                        print(f"  - Found artifact: {art.name} at {art.storage.local_path or art.storage.cloud_url}")
                        return art
        print(f"  - Artifact {name} not found.")
        return None

    def version_code(self, local_path: str, git_repo_url: HttpUrl,
                     commit_message: str, branch_name: Optional[str] = "main") -> Dict[str, Any]:
        """
        Versions source code in a Git repository.
        """
        print(f"Versioning code at {local_path} in {git_repo_url} on branch {branch_name} with message: '{commit_message}'")
        # Placeholder for actual Git operations (e.g., git add, git commit, git push)
        # This would involve using a GitPython library or shell commands.
        # For now, just print a confirmation.
        return {"status": "success", "message": "Code versioned successfully (simulated)."}

    def manage_metadata(self, artifact_name: str, updates: Optional[Dict[str, Any]] = None,
                        keys_to_retrieve: Optional[List[str]] = None) -> Union[Dict[str, Any], None]:
        """
        Manages metadata for a given artifact or the system overall.
        Updates metadata if 'updates' is provided, retrieves specific keys if 'keys_to_retrieve' is provided.
        """
        print(f"Managing metadata for artifact: {artifact_name}")
        # Placeholder for finding the artifact and updating/retrieving its metadata.
        # If artifact_name is a special keyword (e.g., 'system'), update system_metadata.
        if artifact_name == "system" and updates:
            if self.system_metadata is None:
                self.system_metadata = {}
            self.system_metadata.update(updates)
            print(f"  - System metadata updated: {updates}")
            return {"status": "success", "message": "System metadata updated."}
        elif artifact_name == "system" and keys_to_retrieve:
            if self.system_metadata:
                retrieved = {k: self.system_metadata.get(k) for k in keys_to_retrieve}
                print(f"  - Retrieved system metadata: {retrieved}")
                return retrieved
            return {}

        # For individual artifacts
        all_artifacts = (
            self.datasets + self.simulation_results + self.model_weights +
            self.generated_embeddings + self.source_code + self.logs_metrics_metadata +
            self.additional_data
        )

        for art in all_artifacts:
            if art.name == artifact_name:
                if updates:
                    if art.metadata is None:
                        art.metadata = {}
                    art.metadata.update(updates)
                    print(f"  - Artifact {artifact_name} metadata updated: {updates}")
                    return {"status": "success", "message": f"Metadata for {artifact_name} updated."}
                elif keys_to_retrieve:
                    if art.metadata:
                        retrieved = {k: art.metadata.get(k) for k in keys_to_retrieve}
                        print(f"  - Retrieved artifact {artifact_name} metadata: {retrieved}")
                        return retrieved
                    return {}
        print(f"  - Artifact {artifact_name} not found for metadata management.")
        return None

# Example Usage of the methods (outside the main class definition for clarity in outlining)
if __name__ == "__main__":
    # Instantiate the agent
    agent = DataStorageAgent()

    # Example Data Artifacts (re-using previous examples)
    dataset_artifact = DataArtifact(
        name="training_data_v1",
        description="Initial training dataset for model X",
        artifact_type="dataset",
        storage=StorageLocation(cloud_url="s3://my-bucket/datasets/training_data_v1.csv"),
        version_info=DataVersionInfo(
            version_timestamp=datetime.now(),
            data_version_id="dvc-12345",
            description="First version of training data"
        ),
        metadata={"size_gb": 10, "format": "csv"}
    )

    model_weights_artifact = DataArtifact(
        name="model_X_v1_weights",
        description="Weights for model X, trained on training_data_v1",
        artifact_type="model_weights",
        storage=StorageLocation(local_path="models/model_X_v1.pth", cloud_url="gcs://model-repo/model_X_v1.pth"),
        version_info=DataVersionInfo(
            git_repo_url="https://github.com/myorg/myproject",
            commit_hash="abcdef123456",
            branch_name="main",
            version_timestamp=datetime.now()
        ),
        metadata={"framework": "pytorch", "accuracy": 0.85}
    )

    source_code_artifact = DataArtifact(
        name="train_script_v1",
        description="Python script for training model X",
        artifact_type="source_code",
        storage=StorageLocation(local_path="src/train.py", cloud_url="s3://my-bucket/code/train.py"),
        version_info=DataVersionInfo(
            git_repo_url="https://github.com/myorg/myproject",
            commit_hash="abcdef123456",
            branch_name="main",
            version_timestamp=datetime.now()
        ),
        metadata={
            "language": "python",
            "dependencies": [
                "pandas",
                "scikit-learn"
            ]
        }
    )

    # Test store_data
    print("\n--- Testing store_data ---")
    agent.store_data(dataset_artifact)
    agent.store_data(model_weights_artifact)
    agent.store_data(source_code_artifact)
    print(f"Agent datasets after storing: {len(agent.datasets)}")
    print(f"Agent model_weights after storing: {len(agent.model_weights)}")
    print(f"Agent source_code after storing: {len(agent.source_code)}")

    # Test retrieve_data
    print("\n--- Testing retrieve_data ---")
    retrieved_dataset = agent.retrieve_data(name="training_data_v1")
    if retrieved_dataset:
        print(f"Retrieved dataset: {retrieved_dataset.name}, type: {retrieved_dataset.artifact_type}")

    not_found_artifact = agent.retrieve_data(name="non_existent_data")

    # Test version_code
    print("\n--- Testing version_code ---")
    agent.version_code("src/train.py", HttpUrl("https://github.com/myorg/myproject"), "Update training script")

    # Test manage_metadata
    print("\n--- Testing manage_metadata ---")
    agent.manage_metadata(artifact_name="training_data_v1", updates={
        "status": "approved", "tags": ["ml", "raw"]
    })
    retrieved_metadata = agent.manage_metadata(artifact_name="training_data_v1", keys_to_retrieve=["status", "format"])
    if retrieved_metadata:
        print(f"Retrieved metadata for training_data_v1: {retrieved_metadata}")

    agent.manage_metadata(artifact_name="system", updates={
        "deployed_version": "1.0.1", "environment": "production"
    })
    system_meta = agent.manage_metadata(artifact_name="system", keys_to_retrieve=["deployed_version"])
    if system_meta:
        print(f"Retrieved system metadata: {system_meta}")

    print("\n--- Final DataStorageAgent state (partial) ---")
    print(agent.model_dump_json(indent=2))
