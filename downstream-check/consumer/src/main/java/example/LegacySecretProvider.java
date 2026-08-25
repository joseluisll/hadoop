package example;

import java.util.Properties;
import javax.servlet.ServletContext;
import org.apache.hadoop.security.authentication.util.SignerSecretProvider;

/**
 * A SignerSecretProvider of the kind that lives outside Hadoop: it overrides
 * the servlet-flavoured init(), which is the only initialization method that
 * existed before HADOOP-19971.
 *
 * <p>Nothing in Hadoop's tree looks like this, which is why the in-tree tests
 * cannot answer whether the deprecated bridge still calls such a provider.
 */
public class LegacySecretProvider extends SignerSecretProvider {

  private volatile boolean initCalled = false;
  private volatile long recordedValidity = -1;
  private byte[] secret = "legacy-secret".getBytes();

  @Override
  public void init(Properties config, ServletContext servletContext,
      long tokenValidity) throws Exception {
    this.initCalled = true;
    this.recordedValidity = tokenValidity;
  }

  @Override
  public byte[] getCurrentSecret() {
    return secret;
  }

  @Override
  public byte[][] getAllSecrets() {
    return new byte[][] {secret};
  }

  public boolean wasInitCalled() {
    return initCalled;
  }

  public long recordedValidity() {
    return recordedValidity;
  }
}
