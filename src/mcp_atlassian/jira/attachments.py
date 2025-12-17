"""Attachment operations for Jira API."""

import base64
import logging
import os
from pathlib import Path
from typing import Any

from ..models.jira import JiraAttachment
from .client import JiraClient
from .protocols import AttachmentsOperationsProto

# Configure logging
logger = logging.getLogger("mcp-jira")


class AttachmentsMixin(JiraClient, AttachmentsOperationsProto):
    """Mixin for Jira attachment operations."""

    def download_attachment(self, url: str, target_path: str) -> bool:
        """
        Download a Jira attachment to the specified path.

        Args:
            url: The URL of the attachment to download
            target_path: The path where the attachment should be saved

        Returns:
            True if successful, False otherwise
        """
        if not url:
            logger.error("No URL provided for attachment download")
            return False

        try:
            # Convert to absolute path if relative
            if not os.path.isabs(target_path):
                target_path = os.path.abspath(target_path)

            logger.info(f"Downloading attachment from {url} to {target_path}")

            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            # Use the Jira session to download the file
            response = self.jira._session.get(url, stream=True)
            response.raise_for_status()

            # Write the file to disk
            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Verify the file was created
            if os.path.exists(target_path):
                file_size = os.path.getsize(target_path)
                logger.info(
                    f"Successfully downloaded attachment to {target_path} (size: {file_size} bytes)"
                )
                return True
            else:
                logger.error(f"File was not created at {target_path}")
                return False

        except Exception as e:
            logger.error(f"Error downloading attachment: {str(e)}")
            return False

    def download_issue_attachments(
        self, issue_key: str, target_dir: str
    ) -> dict[str, Any]:
        """
        Download all attachments for a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., 'PROJ-123')
            target_dir: The directory where attachments should be saved

        Returns:
            A dictionary with download results
        """
        # Convert to absolute path if relative
        if not os.path.isabs(target_dir):
            target_dir = os.path.abspath(target_dir)

        logger.info(
            f"Downloading attachments for {issue_key} to directory: {target_dir}"
        )

        # Create the target directory if it doesn't exist
        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)

        # Get the issue with attachments
        logger.info(f"Fetching issue {issue_key} with attachments")
        issue_data = self.jira.issue(issue_key, fields="attachment")

        if not isinstance(issue_data, dict):
            msg = f"Unexpected return value type from `jira.issue`: {type(issue_data)}"
            logger.error(msg)
            raise TypeError(msg)

        if "fields" not in issue_data:
            logger.error(f"Could not retrieve issue {issue_key}")
            return {"success": False, "error": f"Could not retrieve issue {issue_key}"}

        # Process attachments
        attachments = []
        results = []

        # Extract attachments from the API response
        attachment_data = issue_data.get("fields", {}).get("attachment", [])

        if not attachment_data:
            return {
                "success": True,
                "message": f"No attachments found for issue {issue_key}",
                "downloaded": [],
                "failed": [],
            }

        # Create JiraAttachment objects for each attachment
        for attachment in attachment_data:
            if isinstance(attachment, dict):
                attachments.append(JiraAttachment.from_api_response(attachment))

        # Download each attachment
        downloaded = []
        failed = []

        for attachment in attachments:
            if not attachment.url:
                logger.warning(f"No URL for attachment {attachment.filename}")
                failed.append(
                    {"filename": attachment.filename, "error": "No URL available"}
                )
                continue

            # Create a safe filename
            safe_filename = Path(attachment.filename).name
            file_path = target_path / safe_filename

            # Download the attachment
            success = self.download_attachment(attachment.url, str(file_path))

            if success:
                downloaded.append(
                    {
                        "filename": attachment.filename,
                        "path": str(file_path),
                        "size": attachment.size,
                    }
                )
            else:
                failed.append(
                    {"filename": attachment.filename, "error": "Download failed"}
                )

        return {
            "success": True,
            "issue_key": issue_key,
            "total": len(attachments),
            "downloaded": downloaded,
            "failed": failed,
        }

    def upload_attachment(self, issue_key: str, file_path: str) -> dict[str, Any]:
        """
        Upload a single attachment to a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., 'PROJ-123')
            file_path: The path to the file to upload

        Returns:
            A dictionary with upload result information
        """
        if not issue_key:
            logger.error("No issue key provided for attachment upload")
            return {"success": False, "error": "No issue key provided"}

        if not file_path:
            logger.error("No file path provided for attachment upload")
            return {"success": False, "error": "No file path provided"}

        try:
            # Convert to absolute path if relative
            if not os.path.isabs(file_path):
                file_path = os.path.abspath(file_path)

            # Check if file exists
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return {"success": False, "error": f"File not found: {file_path}"}

            logger.info(f"Uploading attachment from {file_path} to issue {issue_key}")

            # Use the Jira API to upload the file
            filename = os.path.basename(file_path)
            with open(file_path, "rb") as file:
                attachment = self.jira.add_attachment(
                    issue_key=issue_key, filename=file_path
                )

            if attachment:
                file_size = os.path.getsize(file_path)
                logger.info(
                    f"Successfully uploaded attachment {filename} to {issue_key} (size: {file_size} bytes)"
                )
                return {
                    "success": True,
                    "issue_key": issue_key,
                    "filename": filename,
                    "size": file_size,
                    "id": attachment.get("id")
                    if isinstance(attachment, dict)
                    else None,
                }
            else:
                logger.error(f"Failed to upload attachment {filename} to {issue_key}")
                return {
                    "success": False,
                    "error": f"Failed to upload attachment {filename} to {issue_key}",
                }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error uploading attachment: {error_msg}")
            return {"success": False, "error": error_msg}

    def upload_attachments(
        self, issue_key: str, file_paths: list[str]
    ) -> dict[str, Any]:
        """
        Upload multiple attachments to a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., 'PROJ-123')
            file_paths: List of paths to files to upload

        Returns:
            A dictionary with upload results
        """
        if not issue_key:
            logger.error("No issue key provided for attachment upload")
            return {"success": False, "error": "No issue key provided"}

        if not file_paths:
            logger.error("No file paths provided for attachment upload")
            return {"success": False, "error": "No file paths provided"}

        logger.info(f"Uploading {len(file_paths)} attachments to issue {issue_key}")

        # Upload each attachment
        uploaded = []
        failed = []

        for file_path in file_paths:
            result = self.upload_attachment(issue_key, file_path)

            if result.get("success"):
                uploaded.append(
                    {
                        "filename": result.get("filename"),
                        "size": result.get("size"),
                        "id": result.get("id"),
                    }
                )
            else:
                failed.append(
                    {
                        "filename": os.path.basename(file_path),
                        "error": result.get("error"),
                    }
                )

        return {
            "success": True,
            "issue_key": issue_key,
            "total": len(file_paths),
            "uploaded": uploaded,
            "failed": failed,
        }

    def get_issue_attachments_content(
        self,
        issue_key: str,
        only_images: bool = True,
        max_attachments: int = 5,
        max_bytes_per_attachment: int = 1_000_000,
    ) -> dict[str, Any]:
        """Return attachment contents for a Jira issue encoded as base64.

        This method fetches attachments for the given issue and returns their
        metadata together with an optional base64-encoded representation of the
        file content. It is primarily intended for small binary assets such as
        screenshots or other images that should be directly inspected by an
        AI agent.

        The method applies several safety limits to avoid excessive payload
        sizes:
        - ``max_attachments`` limits the number of attachments included.
        - ``max_bytes_per_attachment`` limits how many bytes are read from
          each attachment. If the file is larger, it is truncated and
          reported as such.

        Args:
            issue_key: Jira issue key (e.g., "PROJ-123").
            only_images: If True, only image attachments ("image/*") are
                returned.
            max_attachments: Maximum number of attachments to include.
            max_bytes_per_attachment: Maximum number of bytes to read per
                attachment before truncating.

        Returns:
            Dictionary describing returned attachments and any failures.
        """

        if max_attachments <= 0 or max_bytes_per_attachment <= 0:
            return {
                "success": False,
                "issue_key": issue_key,
                "error": "max_attachments and max_bytes_per_attachment must be positive",
            }

        logger.info(
            "Fetching attachments content for %s (only_images=%s, max_attachments=%s, max_bytes_per_attachment=%s)",
            issue_key,
            only_images,
            max_attachments,
            max_bytes_per_attachment,
        )

        # Reuse the existing Jira client to fetch the issue with attachment
        # metadata only. This avoids downloading heavy data until we explicitly
        # request the file content below.
        issue_data = self.jira.issue(issue_key, fields="attachment")

        if not isinstance(issue_data, dict):
            msg = f"Unexpected return value type from `jira.issue`: {type(issue_data)}"
            logger.error(msg)
            raise TypeError(msg)

        attachment_field = issue_data.get("fields", {}).get("attachment", [])
        if not attachment_field:
            return {
                "success": True,
                "issue_key": issue_key,
                "total": 0,
                "returned": 0,
                "attachments": [],
                "failed": [],
            }

        attachments: list[JiraAttachment] = []
        for raw_attachment in attachment_field:
            if isinstance(raw_attachment, dict):
                attachments.append(JiraAttachment.from_api_response(raw_attachment))

        # Optionally filter to image/* attachments only.
        def _is_image(attachment: JiraAttachment) -> bool:
            if not attachment.content_type:
                return False
            return attachment.content_type.lower().startswith("image/")

        if only_images:
            attachments = [a for a in attachments if _is_image(a)]

        total_available = len(attachments)
        attachments = attachments[:max_attachments]

        results: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for attachment in attachments:
            if not attachment.url:
                logger.warning("No URL for attachment %s", attachment.filename)
                failed.append(
                    {
                        "filename": attachment.filename,
                        "id": attachment.id,
                        "error": "No URL available for attachment",
                    }
                )
                continue

            try:
                logger.info("Downloading attachment content from %s", attachment.url)
                response = self.jira._session.get(attachment.url, stream=True)
                response.raise_for_status()

                # Read up to max_bytes_per_attachment bytes.
                remaining = max_bytes_per_attachment
                chunks: list[bytes] = []
                truncated = False

                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    if remaining <= 0:
                        truncated = True
                        break
                    if len(chunk) > remaining:
                        chunks.append(chunk[:remaining])
                        truncated = True
                        remaining = 0
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)

                content_bytes = b"".join(chunks)
                content_b64 = base64.b64encode(content_bytes).decode("ascii")

                attachment_info = attachment.to_simplified_dict()
                attachment_info["content_base64"] = content_b64
                attachment_info["truncated"] = truncated

                results.append(attachment_info)

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Error fetching attachment content for %s: %s",
                    attachment.filename,
                    exc,
                )
                failed.append(
                    {
                        "filename": attachment.filename,
                        "id": attachment.id,
                        "error": str(exc),
                    }
                )

        return {
            "success": True,
            "issue_key": issue_key,
            "total": total_available,
            "returned": len(results),
            "attachments": results,
            "failed": failed,
        }
